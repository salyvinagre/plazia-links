"""OIDC entry points and the core server-rendered link-management flow."""

import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.contexts.access.contracts import (
    AccessDeniedError,
    AccessUnavailableError,
    BrowserSession,
    InvalidCredentialsError,
    ResolveOrganizationQuery,
)
from app.contexts.links.contracts import (
    CreateLinkCommand,
    CreatePixelCommand,
    DeleteLinkCommand,
    DeletePixelCommand,
    DeletePoolCommand,
    GetLinkQuery,
    GetPoolQuery,
    GetStatisticsQuery,
    LinkConflictError,
    ListLinksQuery,
    ListPixelsQuery,
    ListPoolsQuery,
    RenamePoolCommand,
    ReservePoolCommand,
    UpdateLinkCommand,
)
from app.interfaces.api.schemas.links import (
    CreateLinkRequest,
    DeleteLinksParams,
    RenamePoolRequest,
    ReservePoolRequest,
    UpdateLinkRequest,
)
from app.interfaces.api.schemas.pixels import CreatePixelRequest
from app.interfaces.authentication import browser_session, csrf, runtime
from app.interfaces.dispatch import mutate, queries, request_context
from app.kernel.ids import LinkId, PixelId, PoolId

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
templates.env.globals["creation_key"] = lambda: uuid4().hex
# Commit/rollback must finish before acknowledging a write or sending a redirect.
Session = Annotated[BrowserSession, Depends(browser_session)]


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303, headers={"Cache-Control": "no-store"})


def _links_redirect(pool_id: str | None = None, pool_page: int = 1) -> RedirectResponse:
    params = {"pool_id": pool_id} if pool_id else {}
    if pool_page > 1:
        params["pool_page"] = str(pool_page)
    path = "/dashboard/links"
    return _redirect(f"{path}?{urlencode(params)}" if params else path)


@router.get("/login")
async def login(request: Request) -> Response:
    auth = runtime(request)
    try:
        location, handle = await auth.browser.begin()
    except AccessUnavailableError as exc:
        raise HTTPException(503, "session_store_unavailable") from exc
    response = _redirect(location)
    response.set_cookie(
        auth.config.login_cookie,
        handle,
        max_age=600,
        httponly=True,
        secure=auth.config.secure,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/auth/callback")
async def callback(request: Request) -> Response:
    auth = runtime(request)
    try:
        for name in ("code", "state"):
            if len(request.query_params.getlist(name)) != 1:
                raise InvalidCredentialsError
        if "error" in request.query_params:
            raise InvalidCredentialsError
        session = await auth.browser.complete(
            request.cookies.get(auth.config.login_cookie, ""),
            request.query_params["state"],
            request.query_params["code"],
        )
        # Sign-in resolves an existing binding; it never provisions tenant authority.
        await queries(request).ask(
            ResolveOrganizationQuery(session.principal),
            context=request_context(request, session.principal),
        )
        await auth.browser.logout(request.cookies.get(auth.config.session_cookie, ""))
        handle = await auth.browser.save(session)
        response: Response = _redirect("/dashboard/links")
        response.set_cookie(
            auth.config.session_cookie,
            handle,
            max_age=max(1, session.expires_at - int(time.time())),
            httponly=True,
            secure=auth.config.secure,
            samesite="lax",
            path="/",
        )
    except InvalidCredentialsError, AccessDeniedError:
        response = templates.TemplateResponse(
            request,
            "identity/error.html",
            {
                "message": (
                    "Sign-in could not be completed. Restart sign-in or contact your administrator."
                ),
            },
            status_code=400,
        )
    except AccessUnavailableError:
        response = templates.TemplateResponse(
            request,
            "identity/error.html",
            {
                "message": "Sign-in is temporarily unavailable. Please try again.",
            },
            status_code=503,
        )
    response.delete_cookie(
        auth.config.login_cookie, secure=auth.config.secure, httponly=True, samesite="lax", path="/"
    )
    return response


@router.get("/signed-out", response_class=HTMLResponse)
async def signed_out(request: Request) -> Response:
    return templates.TemplateResponse(request, "identity/signed_out.html")


@router.post("/logout")
async def logout(request: Request, session: Session) -> Response:
    form = await request.form(max_fields=10, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    auth = runtime(request)
    try:
        await auth.browser.logout(request.cookies.get(auth.config.session_cookie, ""))
    except AccessUnavailableError as exc:
        raise HTTPException(503, "session_store_unavailable") from exc
    response = _redirect("/signed-out")
    response.delete_cookie(
        auth.config.session_cookie,
        secure=auth.config.secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/dashboard")
async def dashboard() -> Response:
    return _redirect("/dashboard/links")


@router.get("/dashboard/links", response_class=HTMLResponse)
async def links(
    request: Request,
    session: Session,
    page: int = Query(1, ge=1, le=100000),
    pool_id: str | None = None,
    pool_page: int = Query(1, ge=1, le=100000),
) -> Response:
    return await _links_page(request, session, page, pool_id, pool_page=pool_page)


async def _links_page(
    request: Request,
    session: BrowserSession,
    page: int,
    pool_id: str | None,
    *,
    pool_page: int = 1,
    pool_error: str | None = None,
    pool_name: str | None = None,
) -> Response:
    context = request_context(request, session.principal)
    organization = await queries(request).ask(
        ResolveOrganizationQuery(session.principal), context=context
    )
    result = await queries(request).ask(
        ListLinksQuery(session.principal, page, 20, PoolId(pool_id) if pool_id else None),
        context=context,
    )
    pools = await queries(request).ask(
        ListPoolsQuery(session.principal, pool_page, 100), context=context
    )
    pool = (
        await queries(request).ask(
            GetPoolQuery(session.principal, PoolId(pool_id)), context=context
        )
        if pool_id
        else None
    )
    return templates.TemplateResponse(
        request,
        "identity/links.html",
        {
            "session": session,
            "organization_name": organization.name,
            "links": result,
            "pools": pools,
            "pool_id": pool_id,
            "pool": pool,
            "statistics": pool.statistics
            if pool
            else await queries(request).ask(GetStatisticsQuery(session.principal), context=context),
            "pool_error": pool_error,
            "pool_name": pool_name,
            "public_base": runtime(request).config.public_base_url.rstrip("/"),
        },
        status_code=422 if pool_error else 200,
        headers={"HX-Push-Url": "false"} if pool_error else {},
    )


@router.post("/dashboard/pools")
async def reserve_pool(request: Request, session: Session) -> Response:
    form = await request.form(max_fields=4, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    data = ReservePoolRequest.model_validate(
        {"name": str(form.get("name", "")) or None, "size": int(str(form.get("size", "")))}
    )
    pool = await mutate(
        request,
        ReservePoolCommand(session.principal, data.size, data.name),
        session.principal,
        key=str(form.get("idempotency_key", "")),
    )
    return _redirect(f"/dashboard/links?pool_id={pool.id}")


@router.post("/dashboard/pools/{pool_id}")
async def rename_pool(
    pool_id: str,
    request: Request,
    session: Session,
    pool_page: int = Query(1, ge=1, le=100000),
) -> Response:
    form = await request.form(max_fields=3, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    name = str(form.get("name", ""))
    try:
        data = RenamePoolRequest.model_validate({"name": name or None})
        await mutate(
            request,
            RenamePoolCommand(session.principal, PoolId(pool_id), data.name),
            session.principal,
            key=str(form.get("idempotency_key", "")),
        )
    except ValidationError:
        return await _links_page(
            request,
            session,
            1,
            pool_id,
            pool_page=pool_page,
            pool_error="Use a pool name of 200 characters or fewer.",
            pool_name=name,
        )
    return _links_redirect(pool_id, pool_page)


@router.post("/dashboard/pools/{pool_id}/delete")
async def delete_pool(
    pool_id: str,
    request: Request,
    session: Session,
    pool_page: int = Query(1, ge=1, le=100000),
) -> Response:
    form = await request.form(max_fields=2, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    await mutate(
        request,
        DeletePoolCommand(session.principal, PoolId(pool_id)),
        session.principal,
        key=str(form.get("idempotency_key", "")),
    )
    return _links_redirect(pool_page=pool_page)


@router.post("/dashboard/links/delete")
async def delete_links(
    request: Request,
    session: Session,
    pool_id: str | None = None,
    pool_page: int = Query(1, ge=1, le=100000),
) -> Response:
    form = await request.form(max_fields=103, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    data = DeleteLinksParams.model_validate(
        {"ids": form.getlist("ids") or None, "pool_id": pool_id, "all": form.get("all", False)}
    )
    await mutate(
        request,
        data.command(session.principal),
        session.principal,
        key=str(form.get("idempotency_key", "")),
    )
    return _links_redirect(pool_id, pool_page)


@router.get("/dashboard/links/new", response_class=HTMLResponse)
async def new_form(request: Request, session: Session) -> Response:
    session.principal.require("links:create")
    await queries(request).ask(
        ResolveOrganizationQuery(session.principal),
        context=request_context(request, session.principal),
    )
    return templates.TemplateResponse(
        request,
        "identity/link_form.html",
        {"session": session, "link_id": None, "values": {}, "error": None},
    )


@router.get("/dashboard/links/{link_id}/edit", response_class=HTMLResponse)
async def edit_form(link_id: str, request: Request, session: Session) -> Response:
    session.principal.require("links:update")
    link = await queries(request).ask(
        GetLinkQuery(session.principal, LinkId(link_id)),
        context=request_context(request, session.principal),
    )
    return templates.TemplateResponse(
        request,
        "identity/link_form.html",
        {"session": session, "link_id": link.id, "values": link, "error": None},
    )


@router.post("/dashboard/links")
async def create_link(request: Request, session: Session) -> Response:
    form = await request.form(max_fields=6, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    values = {
        key: str(form.get(key, "")) or None
        for key in ("destination_url", "title", "notes", "short_code")
    }
    try:
        data = CreateLinkRequest.model_validate(values)
        await mutate(
            request,
            CreateLinkCommand(session.principal, data.draft()),
            session.principal,
            key=str(form.get("idempotency_key", "")),
        )
    except (ValidationError, LinkConflictError) as exc:
        return templates.TemplateResponse(
            request,
            "identity/link_form.html",
            {
                "session": session,
                "link_id": None,
                "values": values,
                "error": "Short code is unavailable."
                if isinstance(exc, LinkConflictError)
                else "Check the destination and field lengths.",
            },
            status_code=409 if isinstance(exc, LinkConflictError) else 422,
            headers={"HX-Push-Url": "false"},
        )
    return _redirect("/dashboard/links")


@router.post("/dashboard/links/{link_id}")
async def update_link(link_id: str, request: Request, session: Session) -> Response:
    form = await request.form(max_fields=6, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    values: dict[str, str | bool | None] = {
        "title": str(form.get("title", "")) or None,
        "notes": str(form.get("notes", "")) or None,
        "is_active": form.get("is_active") == "on",
    }
    if form.get("destination_url"):
        values["destination_url"] = str(form["destination_url"])
    try:
        data = UpdateLinkRequest.model_validate(values)
        await mutate(
            request,
            UpdateLinkCommand(session.principal, LinkId(link_id), data.patch()),
            session.principal,
            key=str(form.get("idempotency_key", "")),
        )
    except ValidationError, ValueError:
        return templates.TemplateResponse(
            request,
            "identity/link_form.html",
            {
                "session": session,
                "link_id": link_id,
                "values": values,
                "error": "Check the destination and field lengths. Enable the link to activate it.",
            },
            status_code=422,
            headers={"HX-Push-Url": "false"},
        )
    return _redirect("/dashboard/links")


@router.post("/dashboard/links/{link_id}/delete")
async def delete_link(
    link_id: str,
    request: Request,
    session: Session,
    pool_id: str | None = None,
    pool_page: int = Query(1, ge=1, le=100000),
) -> Response:
    form = await request.form(max_fields=2, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    await mutate(
        request,
        DeleteLinkCommand(session.principal, LinkId(link_id)),
        session.principal,
        key=str(form.get("idempotency_key", "")),
    )
    return _links_redirect(pool_id, pool_page)


@router.get("/dashboard/pixels", response_class=HTMLResponse)
async def pixels(
    request: Request, session: Session, page: int = Query(1, ge=1, le=100000)
) -> Response:
    return await _pixels_page(request, session, page)


async def _pixels_page(
    request: Request,
    session: BrowserSession,
    page: int = 1,
    *,
    error: str | None = None,
    reference: str | None = None,
    key: str | None = None,
) -> Response:
    context = request_context(request, session.principal)
    organization = await queries(request).ask(
        ResolveOrganizationQuery(session.principal), context=context
    )
    result = await queries(request).ask(ListPixelsQuery(session.principal, page), context=context)
    if page > 1 and not result.items:
        page = max(1, (result.total + result.page_size - 1) // result.page_size)
        return _redirect(f"/dashboard/pixels?page={page}" if page > 1 else "/dashboard/pixels")
    return templates.TemplateResponse(
        request,
        "identity/pixels.html",
        {
            "session": session,
            "organization_name": organization.name,
            "pixels": result,
            "public_base": runtime(request).config.public_base_url.rstrip("/"),
            "error": error,
            "reference": reference,
            "key": key,
        },
        status_code=422 if error else 200,
        headers={"HX-Push-Url": "false"} if error else {},
    )


@router.post("/dashboard/pixels")
async def create_pixel(request: Request, session: Session) -> Response:
    form = await request.form(max_fields=3, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    reference, key = str(form.get("reference", "")), str(form.get("idempotency_key", ""))
    try:
        data = CreatePixelRequest(reference=reference)
    except ValidationError:
        return await _pixels_page(
            request,
            session,
            error="Use a delivery reference of 200 characters or fewer.",
            reference=reference,
            key=key,
        )
    await mutate(
        request, CreatePixelCommand(session.principal, data.draft()), session.principal, key=key
    )
    return _redirect("/dashboard/pixels")


@router.post("/dashboard/pixels/{pixel_id}/delete")
async def delete_pixel(
    pixel_id: str, request: Request, session: Session, page: int = Query(1, ge=1, le=100000)
) -> Response:
    form = await request.form(max_fields=2, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    await mutate(
        request,
        DeletePixelCommand(session.principal, PixelId(pixel_id)),
        session.principal,
        key=str(form.get("idempotency_key", "")),
    )
    return _redirect(f"/dashboard/pixels?page={page}" if page > 1 else "/dashboard/pixels")
