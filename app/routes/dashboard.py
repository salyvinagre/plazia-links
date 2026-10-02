from datetime import UTC, datetime
from html import escape as h

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.security import decode_access_token as decode_jwt
from app.core.security import get_current_user_from_cookie as get_current_user
from app.models.user import User
from app.services.ab_service import get_variant, list_variants
from app.services.analytics_service import get_workspace_summary
from app.services.api_key_service import list_api_keys
from app.services.bio_service import get_bio_link, get_bio_page, get_bio_page_by_slug
from app.services.domain_service import list_workspace_domains
from app.services.email_campaign_service import (
    get_campaign,
    get_template,
    list_campaigns,
    list_contacts,
    list_templates,
    update_campaign_stats,
)
from app.services.invite_service import list_invites, list_members
from app.services.link_service import get_link_by_id, get_links
from app.services.notification_service import check_expiring_links
from app.services.session_service import list_sessions
from app.services.tag_service import get_tags
from app.services.webhook_service import get_webhooks
from app.services.workspace_service import get_workspace, get_workspaces_for_user

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "dashboard/index.html",
        {"user": current_user, "default_ws": default_ws, "workspaces": workspaces},
    )


@router.get("/dashboard/links", response_class=HTMLResponse)
async def links_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    folders = []
    if default_ws:
        try:
            from app.services.folder_service import get_folders as _gf

            folders = await _gf(db, default_ws.id)
        except Exception:
            folders = []
    return templates.TemplateResponse(
        request,
        "dashboard/links.html",
        {
            "user": current_user,
            "workspace_id": default_ws.id if default_ws else "",
            "folders": folders,
        },
    )


@router.get("/dashboard/links/{link_id}", response_class=HTMLResponse)
async def link_detail_page(
    request: Request,
    link_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    link = await get_link_by_id(db, link_id)
    if not link:
        raise HTTPException(status_code=404)
    ws = await get_workspace(db, link.workspace_id)
    if not ws or ws.owner_id != current_user.id:
        raise HTTPException(status_code=403)
    return templates.TemplateResponse(
        request,
        "dashboard/link_detail.html",
        {"user": current_user, "link": link},
    )


@router.get("/dashboard/bio", response_class=HTMLResponse)
async def bio_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    bio = None
    if default_ws:
        bio = await get_bio_page(db, default_ws.id)
    return templates.TemplateResponse(
        request,
        "dashboard/bio.html",
        {"user": current_user, "bio": bio, "workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard/settings.html",
        {"user": current_user},
    )


@router.get("/dashboard/domains", response_class=HTMLResponse)
async def domains_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "dashboard/domains.html",
        {"user": current_user, "workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/email", response_class=HTMLResponse)
async def email_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "dashboard/email.html",
        {"user": current_user, "workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/api-keys", response_class=HTMLResponse)
async def api_keys_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "dashboard/api_keys.html",
        {"user": current_user, "workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/webhooks", response_class=HTMLResponse)
async def webhooks_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "dashboard/webhooks.html",
        {"user": current_user, "workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/tags", response_class=HTMLResponse)
async def tags_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "dashboard/tags.html",
        {"user": current_user, "workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/invites", response_class=HTMLResponse)
async def invites_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "dashboard/invites.html",
        {"user": current_user, "workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/workspaces", response_class=HTMLResponse)
async def workspaces_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    return templates.TemplateResponse(
        request,
        "dashboard/workspaces.html",
        {"user": current_user, "workspaces": workspaces},
    )


@router.get("/dashboard/workspaces/list", response_class=HTMLResponse)
async def workspaces_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    return templates.TemplateResponse(
        request,
        "partials/workspace_list.html",
        {"user": current_user, "workspaces": workspaces},
    )


@router.get("/dashboard/workspaces/new-form", response_class=HTMLResponse)
async def workspace_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/workspace_form.html",
        {},
    )


@router.get("/dashboard/workspaces/{workspace_id}/edit-form", response_class=HTMLResponse)
async def workspace_edit_form(
    request: Request,
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    ws = await get_workspace(db, workspace_id)
    if not ws:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/workspace_form.html",
        {"workspace": ws},
    )


@router.get("/dashboard/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser access required")
    return templates.TemplateResponse(
        request,
        "dashboard/admin_stats.html",
        {"user": current_user},
    )


@router.get("/dashboard/admin/audit", response_class=HTMLResponse)
async def audit_logs_page(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser access required")
    return templates.TemplateResponse(
        request,
        "dashboard/audit_logs.html",
        {"user": current_user},
    )


@router.get("/bio/{slug}", response_class=HTMLResponse)
async def public_bio_page(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    bio = await get_bio_page_by_slug(db, slug)
    if not bio or not bio.is_published:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "bio/public.html",
        {"bio": bio},
    )


# ---- HTMX Partial Routes ----


@router.get("/dashboard/summary", response_class=HTMLResponse)
async def dashboard_summary(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse("")
    summary = await get_workspace_summary(db, default_ws.id, 7)
    return templates.TemplateResponse(
        request,
        "partials/workspace_summary.html",
        dict(summary),
    )


@router.get("/dashboard/links/list", response_class=HTMLResponse)
async def links_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="7" style="text-align:center;padding:3rem '
            "1rem;color:var(--zly-muted);font-family:Space "
            'Grotesk,sans-serif;font-size:0.7rem;letter-spacing:0.05em;">NO '
            "WORKSPACE</td></tr>"
        )
    now = datetime.now(UTC)
    search = request.query_params.get("search") or None
    folder_id = request.query_params.get("folder_id") or None
    if folder_id == "none":
        folder_id = "__none__"  # sentinel for no folder filter handled below
    is_archived_raw = request.query_params.get("is_archived")
    is_archived = (
        True
        if is_archived_raw in ("true", "on", "1")
        else (None if is_archived_raw is None else False)
    )
    # Handle folder none vs all
    if folder_id == "__none__":
        # filter links where folder_id is NULL
        # Use get_links with no folder then filter manually
        links_all, total_all, _ = await get_links(
            db, default_ws.id, page=1, page_size=200, search=search, is_archived=is_archived
        )
        links = [item for item in links_all if not getattr(item, "folder_id", None)]
        total = len(links)
        has_next = False
    else:
        links, total, has_next = await get_links(
            db,
            default_ws.id,
            page=1,
            page_size=50,
            search=search,
            folder_id=folder_id,
            is_archived=is_archived,
        )
    rows = []
    for link in links:
        badge_html = ""
        if getattr(link, "is_archived", False):
            badge_html += '<span class="zly-badge zly-badge-hidden">Archived</span> '
        if link.is_active:
            badge_html += '<span class="zly-badge zly-badge-active">Active</span>'
        else:
            badge_html += '<span class="zly-badge zly-badge-hidden">Inactive</span>'
        if link.expires_at:
            delta = (link.expires_at - now).total_seconds()
            if delta <= 0:
                badge_html += ' <span class="zly-badge zly-badge-danger">Expired</span>'
            elif delta <= 7 * 86400:
                badge_html += (
                    ' <span class="zly-badge zly-badge-warning" '
                    'style="background:rgba(255,107,53,0.12)!important;color:#ff6'
                    'b35!important;">Expiring</span>'
                )
        if link.password_hash:
            badge_html += ' <span class="zly-badge zly-badge-warning">Protected</span>'
        if getattr(link, "max_clicks", None):
            badge_html += (
                ' <span class="zly-badge zly-badge-info" '
                'style="font-size:0.5rem;">'
                f"{link.max_clicks}"
                " max</span>"
            )
        health_badge = ""
        # Skip live HEAD check if link archived/inactive to save time
        if link.is_active and not getattr(link, "is_archived", False):
            try:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    resp = await client.head(link.destination_url, follow_redirects=True)
                    status_code = resp.status_code
                    if 200 <= status_code < 400:
                        health_badge = (
                            ' <span class="zly-badge zly-badge-active" '
                            'style="font-size:0.5rem;">✓ Online</span>'
                        )
                    else:
                        health_badge = (
                            ' <span class="zly-badge zly-badge-danger" '
                            'style="font-size:0.5rem;">✗ '
                            f"{status_code}"
                            "</span>"
                        )
            except Exception:
                health_badge = (
                    ' <span class="zly-badge zly-badge-warning" '
                    'style="font-size:0.5rem;">⚠ Timeout</span>'
                )
        folder_hint = ""
        if getattr(link, "folder_id", None):
            folder_hint = '<span style="font-size:0.55rem;color:var(--zly-muted);">📁</span> '
        rows.append(
            '<tr>\n            <td><input type="checkbox" class="link-check" '
            'value="'
            f"{link.id}"
            '" style="accent-color:var(--zly-emerald);"></td>\n            <td '
            'style="max-width:12rem;">'
            f"{folder_hint}"
            '<code style="font-family:Space '
            "Mono,monospace;font-size:0.75rem;color:var(--zly-emerald);cu"
            'rsor:pointer;" onclick="copyToClipboard(\'/'
            f"{h(link.short_code)}"
            "')\">/"
            f"{h(link.short_code)}"
            "</code></td>\n            <td "
            'style="max-width:16rem;white-space:nowrap;overflow:hidden;te'
            'xt-overflow:ellipsis;">'
            f"{h(link.destination_url)}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.75rem;">'
            f"{getattr(link, 'clicks', 0) or 0}"
            "</td>\n            <td>"
            f"{badge_html}"
            f"{health_badge}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;color:var(--zly-muted);">'
            f"{(link.created_at.strftime('%Y-%m-%d') if link.created_at else '')}"
            "</td>\n            <td "
            'style="text-align:right;white-space:nowrap;">\n                <a '
            'href="/dashboard/links/'
            f"{link.id}"
            '" class="zly-btn zly-btn-secondary" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;">Analytics</a>\n                '
            '<button class="zly-btn zly-btn-secondary" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-get="/dashboard/links/'
            f"{link.id}"
            '/edit-form" hx-target="#edit-link-modal" '
            'hx-swap="innerHTML">Edit</button>\n                <button '
            'class="zly-btn zly-btn-danger" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-delete="/api/v1/workspaces/'
            f"{default_ws.id}"
            "/links/"
            f"{link.id}"
            '" hx-target="#links-tbody" hx-swap="outerHTML" '
            'hx-confirm="Delete this link?">Delete</button>\n            '
            "</td>\n        </tr>"
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="7" style="text-align:center;padding:3rem '
            "1rem;color:var(--zly-muted);font-family:Space "
            'Grotesk,sans-serif;font-size:0.7rem;letter-spacing:0.05em;">NO '
            "LINKS FOUND. TRY CLEARING FILTERS.</td></tr>"
        )
    return HTMLResponse("".join(rows))


@router.get("/dashboard/links/new-form", response_class=HTMLResponse)
async def link_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    folders = []
    if default_ws:
        try:
            from app.services.folder_service import get_folders

            folders = await get_folders(db, default_ws.id)
        except Exception:
            folders = []
    return templates.TemplateResponse(
        request,
        "partials/link_form.html",
        {"workspace_id": default_ws.id if default_ws else "", "folders": folders},
    )


@router.get("/dashboard/links/import-form", response_class=HTMLResponse)
async def link_import_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "partials/bulk_import_form.html",
        {"workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/links/check-expiring", response_class=HTMLResponse)
async def link_check_expiring(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<div style="color:var(--zly-muted);font-size:0.65rem;">NO WORKSPACE</div>'
        )
    result = await check_expiring_links(db, default_ws.id, within_hours=168)
    count = len(result)
    links = result
    if not links:
        return HTMLResponse(
            '<div style="color:var(--zly-emerald);font-size:0.65rem;">✅ No '
            "links expiring within 7 days.</div>"
        )
    rows = "".join(
        (
            '<div style="display:flex;justify-content:space-between;paddi'
            "ng:0.3rem 0;border-bottom:1px solid "
            'var(--zly-line);font-size:0.6rem;"><span '
            'style="font-family:Space Mono,monospace;">/'
            f"{h(item.get('short_code', ''))}"
            '</span><span style="color:var(--zly-muted);">'
            f"{item.get('expires_at', '')}"
            "</span></div>"
        )
        for item in links
    )
    return HTMLResponse(
        '<div style="padding:0.5rem 0;font-size:0.65rem;"><div '
        'style="margin-bottom:0.5rem;"><span '
        'style="color:#ff6b35;">⚠</span> '
        f"{count}"
        " links expiring within 7 days:</div>"
        f"{rows}"
        "</div>"
    )


@router.get("/dashboard/links/{link_id}/edit-form", response_class=HTMLResponse)
async def link_edit_form(
    request: Request,
    link_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    link = await get_link_by_id(db, link_id)
    if not link:
        raise HTTPException(status_code=404)
    folders = []
    try:
        from app.services.folder_service import get_folders

        folders = await get_folders(db, link.workspace_id)
    except Exception:
        pass
    return templates.TemplateResponse(
        request,
        "partials/link_form.html",
        {"link": link, "workspace_id": link.workspace_id, "folders": folders},
    )


@router.get("/dashboard/webhooks/list", response_class=HTMLResponse)
async def webhooks_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="5" style="text-align:center;padding:2rem '
            '1rem;color:var(--zly-muted);">NO WORKSPACE</td></tr>'
        )
    webhooks, _, _ = await get_webhooks(db, default_ws.id)
    rows = []
    for w in webhooks:
        events_str = w.events if w.events else "all"
        badge = (
            '<span class="zly-badge zly-badge-active">Active</span>'
            if w.is_active
            else '<span class="zly-badge zly-badge-hidden">Inactive</span>'
        )
        rows.append(
            '<tr>\n            <td style="font-weight:500;font-family:Space '
            'Grotesk,sans-serif;font-size:0.75rem;">'
            f"{w.name}"
            "</td>\n            <td "
            'style="max-width:16rem;white-space:nowrap;overflow:hidden;te'
            "xt-overflow:ellipsis;font-family:Space "
            'Mono,monospace;font-size:0.7rem;color:var(--zly-muted);">'
            f"{w.url}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;">'
            f"{events_str}"
            "</td>\n            <td>"
            f"{badge}"
            "</td>\n            <td "
            'style="text-align:right;white-space:nowrap;">\n                '
            '<button class="zly-btn zly-btn-secondary" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-get="/dashboard/webhooks/'
            f"{w.id}"
            '/edit-form" hx-target="#webhook-form-modal" '
            'hx-swap="innerHTML">Edit</button>\n                <button '
            'class="zly-btn zly-btn-danger" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-delete="/api/v1/workspaces/'
            f"{default_ws.id}"
            "/webhooks/"
            f"{w.id}"
            '" hx-target="closest tr" hx-swap="outerHTML" hx-confirm="Delete '
            'this webhook?">Delete</button>\n            </td>\n        </tr>'
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="5" style="text-align:center;padding:2rem '
            "1rem;color:var(--zly-muted);font-family:Space "
            'Grotesk,sans-serif;font-size:0.7rem;letter-spacing:0.05em;">NO '
            "WEBHOOKS YET.</td></tr>"
        )
    return HTMLResponse("".join(rows))


@router.get("/dashboard/webhooks/new-form", response_class=HTMLResponse)
async def webhook_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "partials/webhook_form.html",
        {"workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/webhooks/{webhook_id}/edit-form", response_class=HTMLResponse)
async def webhook_edit_form(
    request: Request,
    webhook_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.services.webhook_service import get_webhook

    webhook = await get_webhook(db, webhook_id)
    if not webhook:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/webhook_form.html",
        {"webhook": webhook, "workspace_id": webhook.workspace_id},
    )


@router.get("/dashboard/domains/list", response_class=HTMLResponse)
async def domains_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="4" style="text-align:center;padding:2rem '
            '1rem;color:var(--zly-muted);">NO WORKSPACE</td></tr>'
        )
    domains, _, _ = await list_workspace_domains(db, default_ws.id)
    rows = []
    for d in domains:
        status_badge = (
            '<span class="zly-badge zly-badge-active">Verified</span>'
            if d.is_verified
            else '<span class="zly-badge zly-badge-warning">Pending</span>'
        )
        verify_btn = ""
        if not d.is_verified:
            verify_btn = (
                '<button class="zly-btn zly-btn-secondary" '
                'style="font-size:0.55rem;padding:0.25rem '
                '0.6rem;display:inline-flex;" hx-post="/api/v1/workspaces/'
                f"{default_ws.id}"
                "/domains/"
                f"{d.id}"
                '/verify" hx-target="closest tr" '
                'hx-swap="outerHTML">Verify</button>'
            )
        rows.append(
            '<tr>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.75rem;color:var(--zly-emerald);">'
            f"{d.domain}"
            "</td>\n            <td>"
            f"{status_badge}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;color:var(--zly-muted);">'
            f"{(d.created_at.strftime('%Y-%m-%d') if d.created_at else '')}"
            "</td>\n            <td "
            'style="text-align:right;white-space:nowrap;">'
            f"{verify_btn}"
            '\n                <button class="zly-btn zly-btn-danger" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-delete="/api/v1/workspaces/'
            f"{default_ws.id}"
            "/domains/"
            f"{d.id}"
            '" hx-target="closest tr" hx-swap="outerHTML" hx-confirm="Delete '
            'this domain?">Delete</button>\n            </td>\n        </tr>'
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="4" style="text-align:center;padding:2rem '
            "1rem;color:var(--zly-muted);font-family:Space "
            'Grotesk,sans-serif;font-size:0.7rem;letter-spacing:0.05em;">NO '
            "DOMAINS YET.</td></tr>"
        )
    return HTMLResponse("".join(rows))


@router.get("/dashboard/domains/new-form", response_class=HTMLResponse)
async def domain_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "partials/domain_form.html",
        {"workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/tags/list", response_class=HTMLResponse)
async def tags_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="4" style="text-align:center;padding:2rem '
            '1rem;color:var(--zly-muted);">NO WORKSPACE</td></tr>'
        )
    tags, _, _ = await get_tags(db, default_ws.id)
    rows = []
    for t in tags:
        color_hex = t.color or "#6366f1"
        rows.append(
            '<tr>\n            <td style="font-weight:500;font-family:Space '
            'Grotesk,sans-serif;font-size:0.75rem;">'
            f"{h(t.name)}"
            "</td>\n            <td><span "
            'style="display:inline-block;width:0.75rem;height:0.75rem;bac'
            "kground:"
            f"{color_hex}"
            ';vertical-align:middle;margin-right:0.25rem;"></span><code '
            'style="font-family:Space '
            'Mono,monospace;font-size:0.65rem;color:var(--zly-muted);">'
            f"{h(color_hex)}"
            '</code></td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;color:var(--zly-muted);">'
            f"{(t.created_at.strftime('%Y-%m-%d') if t.created_at else '')}"
            "</td>\n            <td "
            'style="text-align:right;white-space:nowrap;">\n                '
            '<button class="zly-btn zly-btn-secondary" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-get="/dashboard/tags/'
            f"{t.id}"
            '/edit-form" hx-target="#tag-form-modal" '
            'hx-swap="innerHTML">Edit</button>\n                <button '
            'class="zly-btn zly-btn-danger" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-delete="/api/v1/workspaces/'
            f"{default_ws.id}"
            "/tags/"
            f"{t.id}"
            '" hx-target="closest tr" hx-swap="outerHTML" hx-confirm="Delete '
            'this tag?">Delete</button>\n            </td>\n        </tr>'
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="4" style="text-align:center;padding:2rem '
            "1rem;color:var(--zly-muted);font-family:Space "
            'Grotesk,sans-serif;font-size:0.7rem;letter-spacing:0.05em;">NO '
            "TAGS YET.</td></tr>"
        )
    return HTMLResponse("".join(rows))


@router.get("/dashboard/folders", response_class=HTMLResponse)
async def folders_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "dashboard/folders.html",
        {"user": current_user, "workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/tags/new-form", response_class=HTMLResponse)
async def tag_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "partials/tag_form.html",
        {"workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/tags/{tag_id}/edit-form", response_class=HTMLResponse)
async def tag_edit_form(
    request: Request,
    tag_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.services.tag_service import get_tag

    tag = await get_tag(db, tag_id)
    if not tag:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/tag_form.html",
        {"tag": tag, "workspace_id": tag.workspace_id},
    )


@router.get("/dashboard/api-keys/list", response_class=HTMLResponse)
async def api_keys_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="6" style="text-align:center;padding:2rem '
            '1rem;color:var(--zly-muted);">NO WORKSPACE</td></tr>'
        )
    keys, _, _ = await list_api_keys(db, default_ws.id)
    rows = []
    for k in keys:
        last_used = k.last_used_at.strftime("%Y-%m-%d") if k.last_used_at else "Never"
        rows.append(
            '<tr>\n            <td style="font-weight:500;font-family:Space '
            'Grotesk,sans-serif;font-size:0.75rem;">'
            f"{h(k.name)}"
            '</td>\n            <td><code style="font-family:Space '
            "Mono,monospace;font-size:0.65rem;color:var(--zly-muted);curs"
            'or:pointer;" onclick="copyToClipboard(\''
            f"{h(k.prefix)}"
            "...')\">"
            f"{h(k.prefix)}"
            '••••••••</code></td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.65rem;color:var(--zly-muted);">'
            f"{h(k.permissions or 'all')}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;color:var(--zly-muted);">'
            f"{last_used}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;color:var(--zly-muted);">'
            f"{(k.created_at.strftime('%Y-%m-%d') if k.created_at else '')}"
            "</td>\n            <td "
            'style="text-align:right;white-space:nowrap;">\n                '
            '<button class="zly-btn zly-btn-secondary" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-get="/dashboard/api-keys/'
            f"{k.id}"
            '/edit-form" hx-target="#key-form-modal" '
            'hx-swap="innerHTML">Edit</button>\n                <button '
            'class="zly-btn zly-btn-danger" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-delete="/api/v1/workspaces/'
            f"{default_ws.id}"
            "/api-keys/"
            f"{k.id}"
            '" hx-target="closest tr" hx-swap="outerHTML" hx-confirm="Revoke '
            'this API key?">Revoke</button>\n            </td>\n        </tr>'
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="6" style="text-align:center;padding:2rem '
            "1rem;color:var(--zly-muted);font-family:Space "
            'Grotesk,sans-serif;font-size:0.7rem;letter-spacing:0.05em;">NO '
            "API KEYS YET.</td></tr>"
        )
    return HTMLResponse("".join(rows))


@router.get("/dashboard/api-keys/new-form", response_class=HTMLResponse)
async def api_key_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "partials/api_key_form.html",
        {"workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/api-keys/{key_id}/edit-form", response_class=HTMLResponse)
async def api_key_edit_form(
    request: Request,
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.services.api_key_service import get_api_key

    key = await get_api_key(db, key_id)
    if not key:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/api_key_form.html",
        {"key": key, "workspace_id": key.workspace_id},
    )


@router.get("/dashboard/invites/list", response_class=HTMLResponse)
async def invites_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="5" style="text-align:center;padding:2rem '
            '1rem;color:var(--zly-muted);">NO WORKSPACE</td></tr>'
        )
    invites, _, _ = await list_invites(db, default_ws.id)
    rows = []
    for inv in invites:
        status_class = ""
        if inv.status == "pending":
            status_class = "zly-badge-warning"
        elif inv.status == "accepted":
            status_class = "zly-badge-active"
        else:
            status_class = "zly-badge-hidden"
        cancel_btn = ""
        if inv.status == "pending":
            cancel_btn = (
                '<button class="zly-btn zly-btn-danger" '
                'style="font-size:0.55rem;padding:0.25rem '
                '0.6rem;display:inline-flex;" hx-delete="/api/v1/workspaces/'
                f"{default_ws.id}"
                "/invites/"
                f"{inv.id}"
                '" hx-target="closest tr" hx-swap="outerHTML" hx-confirm="Cancel '
                'this invite?">Cancel</button>'
            )
        rows.append(
            '<tr>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.75rem;">'
            f"{h(inv.email)}"
            '</td>\n            <td><span class="zly-badge zly-badge-role">'
            f"{h(inv.role)}"
            '</span></td>\n            <td><span class="zly-badge '
            f"{status_class}"
            '">'
            f"{inv.status.title()}"
            '</span></td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;color:var(--zly-muted);">'
            f"{(inv.created_at.strftime('%Y-%m-%d') if inv.created_at else '')}"
            "</td>\n            <td "
            'style="text-align:right;white-space:nowrap;">'
            f"{cancel_btn}"
            "</td>\n        </tr>"
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="5" style="text-align:center;padding:2rem '
            "1rem;color:var(--zly-muted);font-family:Space "
            'Grotesk,sans-serif;font-size:0.7rem;letter-spacing:0.05em;">NO '
            "INVITES YET.</td></tr>"
        )
    return HTMLResponse("".join(rows))


@router.get("/dashboard/invites/members", response_class=HTMLResponse)
async def members_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="4" style="text-align:center;padding:2rem '
            '1rem;color:var(--zly-muted);">NO WORKSPACE</td></tr>'
        )
    members, _, _ = await list_members(db, default_ws.id)
    rows = []
    for m in members:
        remove_btn = ""
        if m.role != "owner":
            remove_btn = (
                '<button class="zly-btn zly-btn-danger" '
                'style="font-size:0.55rem;padding:0.25rem '
                '0.6rem;display:inline-flex;" hx-delete="/api/v1/workspaces/'
                f"{default_ws.id}"
                "/members/"
                f"{m.user_id}"
                '" hx-target="closest tr" hx-swap="outerHTML" hx-confirm="Remove '
                'this member?">Remove</button>'
            )
        rows.append(
            '<tr>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.75rem;">'
            f"{m.user_id[:8]}"
            '...</td>\n            <td><span class="zly-badge zly-badge-role">'
            f"{m.role}"
            '</span></td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;color:var(--zly-muted);">'
            f"{(m.joined_at.strftime('%Y-%m-%d') if m.joined_at else '')}"
            "</td>\n            <td "
            'style="text-align:right;white-space:nowrap;">'
            f"{remove_btn}"
            "</td>\n        </tr>"
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="4" style="text-align:center;padding:2rem '
            "1rem;color:var(--zly-muted);font-family:Space "
            'Grotesk,sans-serif;font-size:0.7rem;letter-spacing:0.05em;">NO '
            "MEMBERS FOUND.</td></tr>"
        )
    return HTMLResponse("".join(rows))


@router.get("/dashboard/invites/new-form", response_class=HTMLResponse)
async def invite_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "partials/invite_form.html",
        {"workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/sessions", response_class=HTMLResponse)
async def sessions_list(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    current_jti = None
    token = request.cookies.get("zly_token")
    if token:
        try:
            payload = decode_jwt(token) or {}
            current_jti = payload.get("jti")
        except Exception:
            pass
    sessions = await list_sessions(current_user.id, current_jti=current_jti)
    return templates.TemplateResponse(
        request,
        "partials/session_rows.html",
        {"sessions": sessions},
    )


@router.get("/dashboard/bio/links/new-form", response_class=HTMLResponse)
async def bio_link_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    bio_id = ""
    if default_ws:
        bio = await get_bio_page(db, default_ws.id)
        if bio:
            bio_id = bio.id
    return templates.TemplateResponse(
        request,
        "partials/bio_link_form.html",
        {"bio_id": bio_id, "workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/links/{link_id}/variants/list", response_class=HTMLResponse)
async def variants_list(
    request: Request,
    link_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.services.link_service import get_link_by_id

    link = await get_link_by_id(db, link_id)
    if not link:
        raise HTTPException(status_code=404)
    variants, _, _ = await list_variants(db, link_id)
    rows = []
    for v in variants:
        default_badge = (
            '<span class="zly-badge zly-badge-active">Default</span>'
            if v.is_default
            else '<span class="zly-badge zly-badge-hidden">Variant</span>'
        )
        rows.append(
            "<tr>\n            <td "
            'style="max-width:16rem;white-space:nowrap;overflow:hidden;te'
            "xt-overflow:ellipsis;font-family:Space "
            'Mono,monospace;font-size:0.7rem;">'
            f"{h(v.destination_url)}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;">'
            f"{v.weight}"
            "%</td>\n            <td>"
            f"{default_badge}"
            "</td>\n            <td "
            'style="text-align:right;white-space:nowrap;">\n                '
            '<button class="zly-btn zly-btn-secondary" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-get="/dashboard/links/'
            f"{link_id}"
            "/variants/"
            f"{v.id}"
            '/edit-form" hx-target="#variant-form-modal" '
            'hx-swap="innerHTML">Edit</button>\n                <button '
            'class="zly-btn zly-btn-danger" '
            'style="font-size:0.55rem;padding:0.25rem '
            '0.6rem;display:inline-flex;" hx-delete="/api/v1/links/'
            f"{link_id}"
            "/variants/"
            f"{v.id}"
            '" hx-target="closest tr" hx-swap="outerHTML" hx-confirm="Delete '
            'this variant?">Delete</button>\n            </td>\n        </tr>'
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="4" style="text-align:center;padding:2rem '
            "1rem;color:var(--zly-muted);font-family:Space "
            'Grotesk,sans-serif;font-size:0.7rem;letter-spacing:0.05em;">NO '
            "VARIANTS YET. ADD ONE TO START A/B TESTING.</td></tr>"
        )
    return HTMLResponse("".join(rows))


@router.get("/dashboard/links/{link_id}/variants/new-form", response_class=HTMLResponse)
async def variant_new_form(
    request: Request,
    link_id: str,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/variant_form.html",
        {"link_id": link_id},
    )


@router.get(
    "/dashboard/links/{link_id}/variants/{variant_id}/edit-form", response_class=HTMLResponse
)
async def variant_edit_form(
    request: Request,
    link_id: str,
    variant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    variant = await get_variant(db, variant_id)
    if not variant:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/variant_form.html",
        {"variant": variant, "link_id": link_id},
    )


@router.get("/dashboard/folders/list", response_class=HTMLResponse)
async def folders_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="3" '
            'style="text-align:center;padding:2rem;color:var(--zly-muted)'
            ';">NO WORKSPACE</td></tr>'
        )
    try:
        from app.services.folder_service import get_folders

        folders = await get_folders(db, default_ws.id)
    except Exception:
        folders = []
    rows = []
    for f in folders:
        rows.append(
            '<tr>\n            <td style="font-weight:500;font-family:Space '
            'Grotesk,sans-serif;font-size:0.75rem;">'
            f"{h(f.name)}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;color:var(--zly-muted);">'
            f"{(f.created_at.strftime('%Y-%m-%d') if f.created_at else '')}"
            '</td>\n            <td style="text-align:right;">\n                '
            '<button class="zly-btn zly-btn-danger" '
            'style="font-size:0.55rem;padding:0.25rem 0.6rem;" '
            'hx-delete="/api/v1/workspaces/'
            f"{default_ws.id}"
            "/folders/"
            f"{f.id}"
            '" hx-target="closest tr" hx-swap="outerHTML" hx-confirm="Delete '
            'this folder?">Delete</button>\n            </td>\n        </tr>'
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="3" '
            'style="text-align:center;padding:2rem;color:var(--zly-muted)'
            ';font-family:Space Grotesk,sans-serif;font-size:0.65rem;">No '
            "folders yet. Create one to organize links.</td></tr>"
        )
    return HTMLResponse("".join(rows))


@router.get("/dashboard/folders/new-form", response_class=HTMLResponse)
async def folder_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request, "partials/folder_form.html", {"workspace_id": default_ws.id if default_ws else ""}
    )


@router.get("/dashboard/links/{link_id}/rules/list", response_class=HTMLResponse)
async def rules_list(
    request: Request,
    link_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    from app.services.link_service import get_link_by_id as _gl

    link = await _gl(db, link_id)
    if not link:
        raise HTTPException(status_code=404)
    try:
        from app.services.link_rule_service import get_rules

        rules = await get_rules(db, link_id)
    except Exception:
        rules = []
    rows = []
    for r in rules:
        rows.append(
            '<tr>\n            <td><span class="zly-badge zly-badge-role">'
            f"{h(r.type)}"
            '</span></td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;">'
            f"{h(r.match_value)}"
            "</td>\n            <td "
            'style="max-width:14rem;white-space:nowrap;overflow:hidden;te'
            'xt-overflow:ellipsis;font-size:0.7rem;">'
            f"{h(r.destination_url)}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;">'
            f"{r.priority}"
            '</td>\n            <td style="text-align:right;">\n                '
            '<button class="zly-btn zly-btn-danger" '
            'style="font-size:0.55rem;padding:0.25rem 0.6rem;" '
            'hx-delete="/api/v1/links/'
            f"{link_id}"
            "/rules/"
            f"{r.id}"
            '" hx-target="closest tr" hx-swap="outerHTML" hx-confirm="Delete '
            'this rule?">Delete</button>\n            </td>\n        </tr>'
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="5" '
            'style="text-align:center;padding:2rem;color:var(--zly-muted)'
            ';font-family:Space Grotesk,sans-serif;font-size:0.65rem;">No '
            "smart rules yet. Add one to route by geo/device.</td></tr>"
        )
    return HTMLResponse("".join(rows))


@router.get("/dashboard/links/{link_id}/rules/new-form", response_class=HTMLResponse)
async def rule_new_form(
    request: Request,
    link_id: str,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    return templates.TemplateResponse(request, "partials/rule_form.html", {"link_id": link_id})


@router.get("/dashboard/bio/links/{link_id}/edit-form", response_class=HTMLResponse)
async def bio_link_edit_form(
    request: Request,
    link_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    bio_link = await get_bio_link(db, link_id)
    if not bio_link:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/bio_link_form.html",
        {"bio_link": bio_link, "workspace_id": ""},
    )


# -------- Email Campaigns HTMX --------


@router.get("/dashboard/email/contacts/list", response_class=HTMLResponse)
async def email_contacts_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="4" style="text-align:center;padding:2rem '
            '1rem;color:var(--zly-muted);">NO WORKSPACE</td></tr>'
        )
    contacts, _, _ = await list_contacts(db, default_ws.id)
    from app.schemas.email_campaign import EmailContactResponse

    contact_responses = [EmailContactResponse.model_validate(c) for c in contacts]
    request.state.current_workspace_id = default_ws.id
    return templates.TemplateResponse(
        request,
        "partials/email_contact_rows.html",
        {"contacts": contact_responses, "workspace_id": default_ws.id},
    )


@router.get("/dashboard/email/contacts/new-form", response_class=HTMLResponse)
async def email_contact_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "partials/email_contact_form.html",
        {"workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/email/templates/list", response_class=HTMLResponse)
async def email_templates_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="5" style="text-align:center;padding:2rem '
            '1rem;color:var(--zly-muted);">NO WORKSPACE</td></tr>'
        )
    templates_list, _, _ = await list_templates(db, default_ws.id)
    from app.schemas.email_campaign import EmailTemplateResponse

    template_responses = [EmailTemplateResponse.model_validate(t) for t in templates_list]
    return templates.TemplateResponse(
        request,
        "partials/email_template_rows.html",
        {"templates": template_responses, "workspace_id": default_ws.id},
    )


@router.get("/dashboard/email/templates/new-form", response_class=HTMLResponse)
async def email_template_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "partials/email_template_form.html",
        {"workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/email/templates/{template_id}/edit-form", response_class=HTMLResponse)
async def email_template_edit_form(
    request: Request,
    template_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    template = await get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404)
    from app.schemas.email_campaign import EmailTemplateResponse

    return templates.TemplateResponse(
        request,
        "partials/email_template_form.html",
        {
            "template": EmailTemplateResponse.model_validate(template),
            "workspace_id": template.workspace_id,
        },
    )


@router.get("/dashboard/email/campaigns/list", response_class=HTMLResponse)
async def email_campaigns_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<tr><td colspan="6" style="text-align:center;padding:2rem '
            '1rem;color:var(--zly-muted);">NO WORKSPACE</td></tr>'
        )
    campaigns, _, _ = await list_campaigns(db, default_ws.id)
    from app.schemas.email_campaign import EmailCampaignResponse

    campaign_responses = [EmailCampaignResponse.model_validate(c) for c in campaigns]
    return templates.TemplateResponse(
        request,
        "partials/email_campaign_rows.html",
        {"campaigns": campaign_responses, "workspace_id": default_ws.id},
    )


@router.get("/dashboard/email/campaigns/new-form", response_class=HTMLResponse)
async def email_campaign_new_form(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    return templates.TemplateResponse(
        request,
        "partials/email_campaign_form.html",
        {"workspace_id": default_ws.id if default_ws else ""},
    )


@router.get("/dashboard/email/campaigns/{campaign_id}/edit-form", response_class=HTMLResponse)
async def email_campaign_edit_form(
    request: Request,
    campaign_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    campaign = await get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404)
    from app.schemas.email_campaign import EmailCampaignResponse

    return templates.TemplateResponse(
        request,
        "partials/email_campaign_form.html",
        {
            "campaign": EmailCampaignResponse.model_validate(campaign),
            "workspace_id": campaign.workspace_id,
        },
    )


@router.get("/dashboard/email/campaigns/{campaign_id}/stats", response_class=HTMLResponse)
async def email_campaign_stats(
    request: Request,
    campaign_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    campaign = await get_campaign(db, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404)
    await update_campaign_stats(db, campaign_id)
    stats = campaign.stats
    from app.schemas.email_campaign import EmailCampaignResponse

    return templates.TemplateResponse(
        request,
        "partials/email_campaign_stats.html",
        {
            "campaign": EmailCampaignResponse.model_validate(campaign),
            "stats": stats,
            "workspace_id": campaign.workspace_id,
        },
    )


# -------- Admin HTML endpoints --------


@router.get("/dashboard/admin/stats", response_class=HTMLResponse)
async def admin_stats_html(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if not current_user.is_superuser:
        return HTMLResponse(
            '<div style="color:var(--zly-muted);padding:2rem;">Admin access required.</div>'
        )
    from sqlalchemy import func, select

    from app.models.audit import AuditLog
    from app.models.click import Click
    from app.models.email_campaign import EmailCampaign, EmailContact
    from app.models.link import Link
    from app.models.webhook import Webhook
    from app.models.workspace import Workspace, WorkspaceMember

    users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    workspaces = (await db.execute(select(func.count()).select_from(Workspace))).scalar() or 0
    links = (await db.execute(select(func.count()).select_from(Link))).scalar() or 0
    clicks = (await db.execute(select(func.count()).select_from(Click))).scalar() or 0
    webhooks = (await db.execute(select(func.count()).select_from(Webhook))).scalar() or 0
    members = (await db.execute(select(func.count()).select_from(WorkspaceMember))).scalar() or 0
    campaigns = (await db.execute(select(func.count()).select_from(EmailCampaign))).scalar() or 0
    contacts = (await db.execute(select(func.count()).select_from(EmailContact))).scalar() or 0
    audit = (await db.execute(select(func.count()).select_from(AuditLog))).scalar() or 0
    return templates.TemplateResponse(
        request,
        "partials/admin_stats.html",
        {
            "users": users,
            "workspaces": workspaces,
            "links": links,
            "clicks": clicks,
            "webhooks": webhooks,
            "members": members,
            "campaigns": campaigns,
            "contacts": contacts,
            "audit": audit,
        },
    )


@router.get("/dashboard/admin/audit-logs/list", response_class=HTMLResponse)
async def admin_audit_logs_list(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if not current_user.is_superuser:
        return HTMLResponse(
            '<tr><td colspan="6" '
            'style="color:var(--zly-muted);padding:2rem;">Admin access '
            "required.</td></tr>"
        )
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.schemas.audit import AuditLogResponse

    result = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(50))
    logs = [AuditLogResponse.model_validate(item) for item in result.scalars().all()]
    rows = []
    for log in logs:
        action_style = "color:var(--zly-emerald);"
        if log.action in ("delete", "revoke", "remove"):
            action_style = "color:#ff6b35;"
        elif log.action in ("create", "invite", "add"):
            action_style = "color:#22c55e;"
        elif log.action in ("update", "change"):
            action_style = "color:#60a5fa;"
        rows.append(
            '<tr>\n            <td><span style="font-family:Space '
            "Mono,monospace;font-size:0.65rem;"
            f"{action_style}"
            '">'
            f"{log.action}"
            '</span></td>\n            <td style="font-family:Space '
            'Grotesk,sans-serif;font-size:0.65rem;">'
            f"{log.resource_type}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.6rem;color:var(--zly-muted);">'
            f"{(log.resource_id or '')[:12]}"
            '...</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.6rem;color:var(--zly-muted);">'
            f"{(log.user_id or '')[:8]}"
            '...</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.6rem;color:var(--zly-muted);">'
            f"{log.ip_address or '—'}"
            '</td>\n            <td style="font-family:Space '
            'Mono,monospace;font-size:0.6rem;color:var(--zly-muted);">'
            f"{(log.created_at.strftime('%Y-%m-%d %H:%M') if log.created_at else '')}"
            "</td>\n        </tr>"
        )
    if not rows:
        return HTMLResponse(
            '<tr><td colspan="6" '
            'style="text-align:center;padding:2rem;color:var(--zly-muted)'
            ';">No audit logs yet.</td></tr>'
        )
    return HTMLResponse("".join(rows))


# -------- Top Links HTML --------


@router.get("/dashboard/top-links", response_class=HTMLResponse)
async def top_links_html(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    workspaces, _, _ = await get_workspaces_for_user(db, current_user.id)
    default_ws = workspaces[0] if workspaces else None
    if not default_ws:
        return HTMLResponse(
            '<div style="text-align:center;padding:2rem;color:var(--zly-muted);">NO WORKSPACE</div>'
        )
    from app.services.link_service import get_links

    links, total, has_next = await get_links(db, default_ws.id, page=1, page_size=10)
    sorted_links = sorted(links, key=lambda item: item.clicks or 0, reverse=True)
    if not sorted_links:
        return HTMLResponse(
            '<div style="text-align:center;padding:2rem;color:var(--zly-m'
            'uted);font-family:Space Grotesk,sans-serif;font-size:0.7rem;">No '
            "links yet.</div>"
        )
    rows = []
    for i, link in enumerate(sorted_links[:10]):
        rows.append(
            '<div style="display:flex;justify-content:space-between;align'
            "-items:center;padding:0.6rem 0;border-bottom:1px solid "
            'var(--zly-line);">\n            <div '
            'style="display:flex;align-items:center;gap:0.75rem;">\n           '
            '     <span style="font-family:Space '
            "Mono,monospace;font-size:0.6rem;color:var(--zly-muted);width"
            ':1.2rem;">#'
            f"{i + 1}"
            '</span>\n                <code style="font-family:Space '
            'Mono,monospace;font-size:0.7rem;color:var(--zly-emerald);">/'
            f"{h(link.short_code)}"
            "</code>\n            </div>\n            <div "
            'style="display:flex;align-items:center;gap:1rem;">\n              '
            '  <span style="font-family:Space '
            'Mono,monospace;font-size:0.65rem;color:var(--zly-cream);">'
            f"{link.clicks or 0}"
            ' clicks</span>\n                <a href="/dashboard/links/'
            f"{link.id}"
            '" class="zly-btn zly-btn-secondary" '
            'style="font-size:0.55rem;padding:0.2rem 0.5rem;">View</a>\n       '
            "     </div>\n        </div>"
        )
    return HTMLResponse(
        '<div class="zly-card" style="padding:1rem;"><h3 '
        'style="font-size:0.65rem;letter-spacing:0.12em;color:var(--z'
        'ly-muted);margin-bottom:0.5rem;">Top Links by Clicks</h3>'
        f"{''.join(rows)}"
        "</div>"
    )
