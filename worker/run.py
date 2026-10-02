from datetime import UTC
from typing import TypedDict, cast

from arq import create_pool, cron
from arq.connections import ArqRedis, RedisSettings
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db import get_session_factory


class WorkerContext(TypedDict):
    redis: ArqRedis
    session_factory: async_sessionmaker[AsyncSession]


async def startup(ctx: WorkerContext) -> None:
    settings.validate_runtime_profile()
    ctx["redis"] = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    ctx["session_factory"] = get_session_factory()


async def shutdown(ctx: WorkerContext) -> None:
    await ctx["redis"].close()


async def process_click(
    ctx: WorkerContext,
    link_id: str,
    ip: str,
    user_agent: str,
    referrer: str,
    variant_id: str | None = None,
) -> None:
    from app.services.click_service import record_click
    from app.services.geoip_service import resolve_ip

    geo = await resolve_ip(ip)

    async with ctx["session_factory"]() as db:
        try:
            await record_click(
                db,
                link_id=link_id,
                ip=ip,
                user_agent=user_agent,
                referrer=referrer,
                variant_id=variant_id,
                country=geo["country"],
                city=geo["city"],
                latitude=geo["latitude"],
                longitude=geo["longitude"],
            )
            await db.commit()
            from sqlalchemy import select

            from app.models.link import Link
            from app.services.analytics_service import invalidate_analytics_cache

            link_result = await db.execute(select(Link).where(Link.id == link_id))
            link_row = link_result.scalar_one_or_none()
            if link_row:
                await invalidate_analytics_cache(link_id, link_row.workspace_id)
        except Exception:
            await db.rollback()
            raise


async def check_expiring_links_worker(ctx: WorkerContext, workspace_id: str) -> None:
    from app.services.notification_service import check_expiring_links

    async with ctx["session_factory"]() as db:
        try:
            await check_expiring_links(db, workspace_id)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def sweep_expiring_links(ctx: WorkerContext) -> None:
    from sqlalchemy import select

    from app.models.workspace import Workspace

    async with ctx["session_factory"]() as db:
        result = await db.execute(select(Workspace.id))
        workspace_ids = [row[0] for row in result.all()]
    for ws_id in workspace_ids:
        await check_expiring_links_worker(ctx, ws_id)


async def send_invite_email_job(
    ctx: WorkerContext,
    invite_id: str,
    to_email: str,
    workspace_name: str,
    invited_by_name: str,
    invite_url: str,
    expires_at: str,
) -> None:
    from app.services.email_service import send_invite_email

    await send_invite_email(
        invite_id=invite_id,
        to_email=to_email,
        workspace_name=workspace_name,
        invited_by_name=invited_by_name,
        invite_url=invite_url,
        expires_at=expires_at,
    )


async def send_password_reset_email_job(
    ctx: WorkerContext, user_id: str, to_email: str, reset_url: str, expires_at: str
) -> None:
    from app.services.email_service import send_password_reset_email

    await send_password_reset_email(
        user_id=user_id,
        to_email=to_email,
        reset_url=reset_url,
        expires_at=expires_at,
    )


async def send_expiry_alert_email_job(
    ctx: WorkerContext,
    link_id: str,
    to_email: str,
    link_title: str,
    short_code: str,
    short_url: str,
    destination_url: str,
    expires_at: str,
    hours_remaining: int,
    total_clicks: int,
) -> None:
    from app.services.email_service import send_expiry_alert_email

    await send_expiry_alert_email(
        link_id=link_id,
        to_email=to_email,
        link_title=link_title,
        short_code=short_code,
        short_url=short_url,
        destination_url=destination_url,
        expires_at=expires_at,
        hours_remaining=hours_remaining,
        total_clicks=total_clicks,
    )


async def deliver_webhook(ctx: WorkerContext, delivery_id: str) -> None:
    from app.services.webhook_delivery_service import deliver_webhook as _deliver

    async with ctx["session_factory"]() as db:
        try:
            await _deliver(db, delivery_id)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def cleanup_old_data(ctx: WorkerContext) -> None:
    from datetime import datetime, timedelta

    from sqlalchemy import delete

    from app.config import settings
    from app.models.audit import AuditLog
    from app.models.click import Click
    from app.models.email_campaign import EmailCampaignClick, EmailCampaignOpen

    if not settings.data_retention_enabled:
        return

    cutoff = datetime.now(UTC) - timedelta(days=settings.click_retention_days)

    async with ctx["session_factory"]() as db:
        try:
            result = await db.execute(delete(Click).where(Click.timestamp < cutoff))
            deleted_clicks = cast(CursorResult[tuple[object, ...]], result).rowcount

            result = await db.execute(
                delete(EmailCampaignOpen).where(EmailCampaignOpen.opened_at < cutoff)
            )
            deleted_opens = cast(CursorResult[tuple[object, ...]], result).rowcount

            result = await db.execute(
                delete(EmailCampaignClick).where(EmailCampaignClick.clicked_at < cutoff)
            )
            deleted_click_events = cast(CursorResult[tuple[object, ...]], result).rowcount

            audit_cutoff = datetime.now(UTC) - timedelta(days=365)
            result = await db.execute(delete(AuditLog).where(AuditLog.created_at < audit_cutoff))
            deleted_audits = cast(CursorResult[tuple[object, ...]], result).rowcount

            await db.commit()
            from app.core.logging import get_logger

            logger = get_logger(__name__)
            logger.info(
                "Data retention cleanup complete",
                extra={
                    "clicks": deleted_clicks,
                    "opens": deleted_opens,
                    "click_events": deleted_click_events,
                    "audit_logs": deleted_audits,
                    "retention_days": settings.click_retention_days,
                },
            )
        except Exception:
            await db.rollback()
            raise


async def send_campaign_job(
    ctx: WorkerContext, campaign_id: str, contact_ids: list[str], base_url: str
) -> None:
    from app.services.email_campaign_service import send_campaign_sync

    async with ctx["session_factory"]() as db:
        try:
            await send_campaign_sync(db, campaign_id, contact_ids, base_url)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


class WorkerSettings:
    functions = [
        process_click,
        check_expiring_links_worker,
        sweep_expiring_links,
        send_invite_email_job,
        send_password_reset_email_job,
        send_expiry_alert_email_job,
        deliver_webhook,
        send_campaign_job,
        cleanup_old_data,
    ]
    cron_jobs = [
        cron("worker.run.cleanup_old_data", hour=3, minute=0),
        cron("worker.run.sweep_expiring_links", minute=0),
    ]
    if settings.auth_mode == "identity":
        functions = [process_click, cleanup_old_data]
        cron_jobs = [cron("worker.run.cleanup_old_data", hour=3, minute=0)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    keep_result_seconds = 3600
    max_jobs = 10
    poll_delay = 0.5
