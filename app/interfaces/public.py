"""Anonymous waiting page and public redirects use the same link identity."""

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, ValidationError
from shared_kernel.contacts import NormalizedEmail

from app.contexts.links.contracts import Destination, ResolveLinkQuery, SubscribeLinkCommand
from app.interfaces.authentication import runtime
from app.interfaces.dispatch import commands, queries, request_context

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


class SubscriptionForm(BaseModel):
    email: EmailStr


def public_host(request: Request) -> None:
    if request.url.hostname != urlsplit(runtime(request).config.public_base_url).hostname:
        raise HTTPException(404, "link_not_found")


@router.get("/{short_code}")
async def resolve(short_code: str, request: Request) -> Response:
    public_host(request)
    link = await queries(request).ask(ResolveLinkQuery(short_code))
    if not link.is_active:
        raise HTTPException(410, "link_disabled")
    if link.destination_url is None:
        return templates.TemplateResponse(
            request,
            "public/waiting.html",
            {"short_code": short_code, "result": None, "error": None},
            headers={"Cache-Control": "no-store"},
        )
    Destination(link.destination_url)
    return RedirectResponse(
        link.destination_url, status_code=307, headers={"Cache-Control": "no-store"}
    )


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
