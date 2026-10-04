"""Anonymous waiting page and public redirects use the same link identity."""

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from shared_kernel.contacts import NormalizedEmail

from app.contexts.links.contracts import (
    VISIT_FAILURE,
    Destination,
    RecordVisitCommand,
    ResolveLinkQuery,
    SubscribeLinkCommand,
)
from app.interfaces.api.schemas.links import SubscriptionForm
from app.interfaces.authentication import runtime
from app.interfaces.dispatch import commands, queries, request_context
from app.platform.logging import get_logger

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


def public_host(request: Request) -> None:
    if request.url.hostname != urlsplit(runtime(request).config.public_base_url).hostname:
        raise HTTPException(404, "link_not_found")


@router.get("/{short_code}")
async def resolve(short_code: str, request: Request) -> Response:
    public_host(request)
    link = await queries(request).ask(
        ResolveLinkQuery(short_code), context=request_context(request)
    )
    if not link.is_active:
        raise HTTPException(410, "link_disabled")
    if link.destination_url is not None:
        Destination(link.destination_url)
    response = (
        templates.TemplateResponse(
            request,
            "public/waiting.html",
            {"short_code": short_code, "result": None, "error": None},
            headers={"Cache-Control": "no-store"},
        )
        if link.destination_url is None
        else RedirectResponse(
            link.destination_url, status_code=307, headers={"Cache-Control": "no-store"}
        )
    )
    try:
        async with asyncio.timeout(0.25):
            await commands(request).dispatch(
                RecordVisitCommand(
                    link.id,
                    short_code,
                    "waiting" if link.destination_url is None else "redirect",
                ),
                context=request_context(request),
            )
    except Exception as error:
        get_logger(__name__).warning(
            "Visit recording failed", extra={"error_type": type(error).__name__}
        )
        telemetry = getattr(request.app.state, "telemetry", None)
        if telemetry is not None:
            telemetry.metrics.emit(VISIT_FAILURE, value=1)
    return response


@router.post("/{short_code}/subscriptions")
async def subscribe(short_code: str, request: Request) -> Response:
    public_host(request)
    expected = runtime(request).config.public_base_url.rstrip("/")
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") != expected:
        raise HTTPException(403, "origin_rejected")
    form = await request.form(max_fields=2, max_files=0)
    try:
        email = SubscriptionForm(email=str(form.get("email", ""))).email
        result = await commands(request).dispatch(
            SubscribeLinkCommand(short_code, NormalizedEmail(str(email))),
            context=request_context(request),
        )
    except ValidationError:
        return templates.TemplateResponse(
            request,
            "public/waiting.html",
            {"short_code": short_code, "result": None, "error": "Enter a valid email address."},
            status_code=422,
            headers={"Cache-Control": "no-store"},
        )
    return templates.TemplateResponse(
        request,
        "public/waiting.html",
        {"short_code": short_code, "result": result, "error": None},
        headers={"Cache-Control": "no-store"},
    )
