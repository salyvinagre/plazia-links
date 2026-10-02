"""OIDC entry points and the core server-rendered link-management flow."""

import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.access.contracts import (
    AccessDeniedError,
    AccessUnavailableError,
    BrowserSession,
    InvalidCredentialsError,
)
from app.contexts.links.contracts import LinkConflictError
from app.core.dependencies import get_db
from app.core.identity import browser_session, csrf, runtime
from app.platform.access import link_management, workspace_access
from app.schemas.managed_link import CreateLinkRequest, UpdateLinkRequest

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
Db = Annotated[AsyncSession, Depends(get_db)]
Session = Annotated[BrowserSession, Depends(browser_session)]


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303, headers={"Cache-Control": "no-store"})


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
async def callback(request: Request, db: Db) -> Response:
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
        # A token does not auto-provision a workspace or turn the first visitor into its owner.
        await workspace_access(db).resolve(session.principal)
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
async def links(request: Request, db: Db, session: Session, page: int = Query(1, ge=1)) -> Response:
    workspace = await workspace_access(db).resolve(session.principal)
    result = await link_management(db, session.principal).list(page, 20)
    return templates.TemplateResponse(
        request,
        "identity/links.html",
        {
            "session": session,
            "workspace_name": workspace.name,
            "links": result,
            "public_base": runtime(request).config.public_base_url.rstrip("/"),
        },
    )


@router.get("/dashboard/links/new", response_class=HTMLResponse)
async def new_form(request: Request, db: Db, session: Session) -> Response:
    session.principal.require("create:links")
    await workspace_access(db).resolve(session.principal)
    return templates.TemplateResponse(
        request,
        "identity/link_form.html",
        {
            "session": session,
            "link_id": None,
            "values": {},
            "error": None,
        },
    )


@router.get("/dashboard/links/{link_id}/edit", response_class=HTMLResponse)
async def edit_form(link_id: str, request: Request, db: Db, session: Session) -> Response:
    session.principal.require("update:links")
    link = await link_management(db, session.principal).get(link_id)
    return templates.TemplateResponse(
        request,
        "identity/link_form.html",
        {
            "session": session,
            "link_id": link.id,
            "values": link,
            "error": None,
        },
    )


@router.post("/dashboard/links")
async def create_link(request: Request, db: Db, session: Session) -> Response:
    form = await request.form(max_fields=10, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    values = {
        key: str(form.get(key, "")) for key in ("destination_url", "title", "notes", "short_code")
    }
    manager = link_management(db, session.principal)
    try:
        data = CreateLinkRequest.model_validate({k: v or None for k, v in values.items()})
        await manager.create(data.draft())
    except (ValidationError, LinkConflictError) as exc:
        message = (
            "This short code is already in use."
            if isinstance(exc, LinkConflictError)
            else (
                "Check the URL and field lengths. "
                "Codes use 3–10 letters, numbers, underscores or hyphens."
            )
        )
        return templates.TemplateResponse(
            request,
            "identity/link_form.html",
            {
                "session": session,
                "link_id": None,
                "values": values,
                "error": message,
            },
            status_code=409 if isinstance(exc, LinkConflictError) else 422,
        )
    return _redirect("/dashboard/links")


@router.post("/dashboard/links/{link_id}")
async def update_link(link_id: str, request: Request, db: Db, session: Session) -> Response:
    form = await request.form(max_fields=10, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    values: dict[str, str | bool | None] = {
        "destination_url": str(form.get("destination_url", "")),
        "title": str(form.get("title", "")) or None,
        "notes": str(form.get("notes", "")) or None,
        "is_active": form.get("is_active") == "on",
    }
    manager = link_management(db, session.principal)
    try:
        await manager.update(link_id, UpdateLinkRequest.model_validate(values).patch())
    except ValidationError:
        return templates.TemplateResponse(
            request,
            "identity/link_form.html",
            {
                "session": session,
                "link_id": link_id,
                "values": values,
                "error": "Check the destination URL and field lengths.",
            },
            status_code=422,
        )
    return _redirect("/dashboard/links")


@router.post("/dashboard/links/{link_id}/delete")
async def delete_link(link_id: str, request: Request, db: Db, session: Session) -> Response:
    form = await request.form(max_fields=10, max_files=0)
    csrf(request, session, str(form.get("csrf_token", "")))
    await link_management(db, session.principal).delete(link_id)
    return _redirect("/dashboard/links")
