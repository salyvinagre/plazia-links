import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.contexts.links.contracts import ClickDraft
from app.core.dependencies import get_db
from app.core.logging import get_logger
from app.core.security import validate_private_url
from app.core.user_agent import extract_domain, parse_user_agent
from app.db import get_session_factory
from app.models.ab import ABVariant
from app.platform.links import click_recorder
from app.services.ab_service import list_variants, select_variant
from app.services.link_service import get_link_by_code

logger = get_logger(__name__)


async def _fire_webhooks(workspace_id: str, event: str, payload: Mapping[str, JsonValue]) -> None:
    from app.services.webhook_service import trigger_webhooks

    factory = get_session_factory()
    async with factory() as session:
        try:
            await trigger_webhooks(session, workspace_id, event, payload)
            await session.commit()
        except Exception:
            await session.rollback()


router = APIRouter()


@router.get("/{short_code}")
async def redirect(
    short_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    from urllib.parse import urlparse

    from app.services.domain_service import get_workspace_by_domain

    host = (request.url.hostname or "").lower().rstrip(".")
    identity_profile = getattr(request.app.state, "auth_mode", "legacy") == "identity"
    public_base = (
        request.app.state.identity_config.public_base_url if identity_profile else settings.base_url
    )
    primary_host = (urlparse(public_base).hostname or "").lower().rstrip(".")
    workspace_id = None
    if host != primary_host:
        workspace_id = await get_workspace_by_domain(db, host)
        if workspace_id is None:
            raise HTTPException(status_code=404, detail="Unknown short-link domain")

    # Global codes remain unique. Custom domains may publish only their own
    # workspace's links; unknown domains must never fall back to global lookup.
    link = await get_link_by_code(db, short_code)
    if link is None or (workspace_id is not None and link.workspace_id != workspace_id):
        raise HTTPException(status_code=404, detail="Link not found")
    if not link.is_active or getattr(link, "is_archived", False):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Link is inactive")

    now = datetime.now(UTC)
    if link.activate_at and link.activate_at > now:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not yet active")
    if link.expires_at and link.expires_at < now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Link has expired")
    # Max clicks guard
    if link.max_clicks is not None:
        from sqlalchemy import func, select

        from app.models.click import Click

        cnt = await db.execute(
            select(func.count()).select_from(Click).where(Click.link_id == link.id)
        )
        if (cnt.scalar() or 0) >= link.max_clicks:
            raise HTTPException(
                status_code=status.HTTP_410_GONE, detail="Link has reached its click limit"
            )

    if link.password_hash:
        password = request.query_params.get("password", "")
        from app.core.security import verify_password as check_pw

        if not password or not check_pw(password, link.password_hash):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password required",
                headers={"X-Link-Id": link.id, "X-Require-Password": "true"},
            )

    # Smart rules evaluation (geo/device/os/referrer)
    try:
        from app.services.geoip_service import resolve_ip as _resolve_ip
        from app.services.link_rule_service import evaluate_rules, get_rules

        rules = await get_rules(db, link.id)
        if rules:
            ip_for_geo = request.client.host if request.client else ""
            ctx = {}
            try:
                geo = await _resolve_ip(ip_for_geo) if ip_for_geo else None
                if geo:
                    ctx["country"] = geo.get("country")
                    ctx["city"] = geo.get("city")
            except Exception:
                pass
            ua_for_rules = request.headers.get("user-agent", "")
            parsed_for_rules = parse_user_agent(ua_for_rules)
            ctx["device"] = parsed_for_rules.get("device_type")
            ctx["os"] = parsed_for_rules.get("os")
            ctx["referrer"] = request.headers.get("referer") or request.headers.get("referrer")
            ctx["accept_language"] = request.headers.get("accept-language")
            matched = evaluate_rules(rules, ctx)
            if matched:
                target_url = matched
                selected_variant = None
                # Skip variant selection if rule matched
                variants: list[ABVariant] = []
            else:
                # No rule matched, fall through to variant/primary
                variants_list = await list_variants(db, link.id)
                variants, _, _ = (
                    variants_list if isinstance(variants_list, tuple) else (variants_list, 0, False)
                )
                target_url = link.destination_url
                selected_variant = None
                if variants:
                    selected_variant = select_variant(variants)
                    if selected_variant:
                        target_url = selected_variant.destination_url
        else:
            variants_list = await list_variants(db, link.id)
            variants, _, _ = (
                variants_list if isinstance(variants_list, tuple) else (variants_list, 0, False)
            )
            target_url = link.destination_url
            selected_variant = None
            if variants:
                selected_variant = select_variant(variants)
                if selected_variant:
                    target_url = selected_variant.destination_url
    except Exception:
        variants_list = await list_variants(db, link.id)
        variants, _, _ = (
            variants_list if isinstance(variants_list, tuple) else (variants_list, 0, False)
        )
        target_url = link.destination_url
        selected_variant = None
        if variants:
            selected_variant = select_variant(variants)
            if selected_variant:
                target_url = selected_variant.destination_url

    try:
        validate_private_url(target_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # Do not cache a bare destination: cache hits used to bypass revocation,
    # password/state changes, domain checks and click recording.

    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent")
    referer = request.headers.get("referer")
    parsed = parse_user_agent(ua)

    await click_recorder(db).record(
        ClickDraft(link.id, ip, ua, referer, selected_variant.id if selected_variant else None)
    )

    if not identity_profile:
        asyncio.create_task(
            _fire_webhooks(
                link.workspace_id,
                "click.created",
                {
                    "event": "click.created",
                    "link_id": link.id,
                    "short_code": link.short_code,
                    "destination_url": target_url,
                    "variant_id": selected_variant.id if selected_variant else None,
                    "browser": parsed["browser"],
                    "os": parsed["os"],
                    "device_type": parsed["device_type"],
                    "referrer_domain": extract_domain(referer),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        )

    return Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"location": target_url},
    )
