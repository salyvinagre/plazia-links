"""Organization-owned email tracking, with the same API language as links."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from shared_http.fastapi import ApiErrorResponse, LinkedResponse, NavigationFacts, linked

from app.contexts.links.contracts import (
    CreatePixelCommand,
    DeletePixelCommand,
    GetPixelQuery,
    ListPixelsQuery,
)
from app.interfaces.api.schemas.links import PageResponse, Pagination
from app.interfaces.api.schemas.pixels import (
    CreatePixelRequest,
    PixelIdText,
    PixelReadResponse,
    PixelResponse,
)
from app.interfaces.authentication import Creator, Deleter, KeyHeader, Reader, runtime
from app.interfaces.dispatch import mutate, queries, request_context
from app.kernel.api import ApiContract
from app.kernel.ids import PixelId

router = APIRouter(
    prefix=ApiContract.path,
    tags=["pixels"],
    responses={
        status: {"model": ApiErrorResponse} for status in (400, 401, 403, 404, 409, 422, 503)
    },
)


@router.post("/pixels", response_model=PixelResponse, status_code=201, operation_id="create_pixel")
async def create_pixel(
    data: CreatePixelRequest, request: Request, response: Response, actor: Creator, _key: KeyHeader
) -> PixelResponse:
    """Create one pixel per email delivery. Retries replay its original identity and URL."""
    pixel = await mutate(request, CreatePixelCommand(actor, data.draft()), actor)
    response.headers["Location"] = ApiContract.resource("pixels", pixel.id)
    return PixelResponse.from_application(pixel, runtime(request).config.public_base_url)


@router.get("/pixels", operation_id="list_pixels")
@linked(format="hal")
async def list_pixels(
    request: Request, actor: Reader, pagination: Annotated[Pagination, Query()]
) -> LinkedResponse[PageResponse[PixelReadResponse]]:
    """List retained organization pixels with forward navigation and request statistics."""
    result = await queries(request).ask(
        ListPixelsQuery(actor, pagination.page(actor, "pixels"), pagination.limit),
        context=request_context(request, actor),
    )
    return LinkedResponse(
        PageResponse[PixelReadResponse](
            items=[
                PixelReadResponse.from_read(pixel, runtime(request).config.public_base_url)
                for pixel in result.items
            ],
            total=result.total,
        ),
        NavigationFacts(
            next_token=pagination.next_token(actor, "pixels", result.page, result.has_next)
        ),
    )


@router.get("/pixels/{pixel_id}", response_model=PixelReadResponse, operation_id="get_pixel")
async def get_pixel(
    pixel_id: Annotated[PixelIdText, Path(description="Canonical pixel identifier.")],
    request: Request,
    actor: Reader,
) -> PixelReadResponse:
    """Read a delivery's pixel and its observed image requests in the current organization."""
    pixel = await queries(request).ask(
        GetPixelQuery(actor, PixelId(pixel_id)), context=request_context(request, actor)
    )
    return PixelReadResponse.from_read(pixel, runtime(request).config.public_base_url)


@router.delete("/pixels/{pixel_id}", status_code=204, operation_id="delete_pixel")
async def delete_pixel(
    pixel_id: Annotated[PixelIdText, Path(description="Canonical pixel identifier.")],
    request: Request,
    actor: Deleter,
    _key: KeyHeader,
) -> None:
    """Revoke a pixel URL and remove its request aggregate. Repeated keys replay success."""
    await mutate(request, DeletePixelCommand(actor, PixelId(pixel_id)), actor)
