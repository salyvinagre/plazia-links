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
    PixelCode,
    RecordPixelRequestCommand,
    RecordVisitCommand,
    ResolveLinkQuery,
    ResolvePixelQuery,
    SubscribeLinkCommand,
)
from app.interfaces.api.schemas.links import SubscriptionForm
from app.interfaces.authentication import runtime
from app.interfaces.dispatch import commands, queries, request_context
from app.platform.logging import get_logger

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


class PublicResponses:
    # GIF89a, 1×1 transparent image; no external asset or runtime generation.
    PIXEL = bytes.fromhex(
        "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
    )

    @staticmethod
    async def record(
        request: Request, command: RecordVisitCommand | RecordPixelRequestCommand
    ) -> None:
        try:
            async with asyncio.timeout(0.25):
                await commands(request).dispatch(command, context=request_context(request))
        except Exception as error:
            get_logger(__name__).warning(
                "Public request recording failed", extra={"error_type": type(error).__name__}
            )
            telemetry = getattr(request.app.state, "telemetry", None)
            if telemetry is not None:
                telemetry.metrics.emit(VISIT_FAILURE, value=1)


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
    await PublicResponses.record(
        request,
        RecordVisitCommand(
            link.id, short_code, "waiting" if link.destination_url is None else "redirect"
        ),
    )
    return response


@router.api_route("/pixels/{code}.gif", methods=["GET", "HEAD"])
async def pixel(code: str, request: Request) -> Response:
    """Deliver an image without visitor identifiers; HEAD never records a fetch."""
    public_host(request)
    try:
        PixelCode(code)
    except ValueError as error:
        raise HTTPException(404, "pixel_not_found") from error
    id = await queries(request).ask(ResolvePixelQuery(code), context=request_context(request))
    response = Response(
        PublicResponses.PIXEL if request.method == "GET" else b"",
        media_type="image/gif",
        headers={"Cache-Control": "no-store", "Content-Length": str(len(PublicResponses.PIXEL))},
    )
    if request.method == "GET":
        await PublicResponses.record(request, RecordPixelRequestCommand(id, code))
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
