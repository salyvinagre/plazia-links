"""JSON adapters dispatch CQRS intents; persistence never crosses this boundary."""

from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, Response, Security
from shared_http.fastapi import ApiErrorResponse, LinkedResponse, NavigationFacts, linked

from app.contexts.access.contracts import Principal
from app.contexts.links.contracts import (
    CreateLinkCommand,
    DeleteLinkCommand,
    GetLinkQuery,
    ListLinksQuery,
    ListPoolsQuery,
    ReservePoolCommand,
    UpdateLinkCommand,
)
from app.interfaces.api.schemas.links import (
    CreateLinkRequest,
    LinkFilter,
    LinkResponse,
    PageResponse,
    Pagination,
    PoolResponse,
    ReservePoolRequest,
    UpdateLinkRequest,
)
from app.interfaces.authentication import api_principal, runtime
from app.interfaces.dispatch import mutate, queries, request_context
from app.kernel.api import ApiContract
from app.kernel.ids import LinkId, PoolId

router = APIRouter(
    prefix=ApiContract.path,
    tags=["links"],
    responses={
        status: {"model": ApiErrorResponse} for status in (400, 401, 403, 404, 409, 422, 503)
    },
)
KeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        description="Required mutation key. Retries replay the original result.",
    ),
]
Reader = Annotated[Principal, Security(api_principal, scopes=["links:read"])]
Creator = Annotated[Principal, Security(api_principal, scopes=["links:create"])]
Updater = Annotated[Principal, Security(api_principal, scopes=["links:update"])]
Deleter = Annotated[Principal, Security(api_principal, scopes=["links:delete"])]


@router.get("/links", operation_id="list_links")
@linked(format="hal")
async def list_links(
    request: Request, actor: Reader, filters: Annotated[LinkFilter, Query()]
) -> LinkedResponse[PageResponse[LinkResponse]]:
    """List the current organization’s links with bounded forward navigation."""
    result = await queries(request).ask(
        ListLinksQuery(
            actor,
            filters.page(actor, "links"),
            filters.limit,
            PoolId(filters.pool_id) if filters.pool_id else None,
        ),
        context=request_context(request, actor),
    )
    return LinkedResponse(
        PageResponse[LinkResponse](
            items=[
                LinkResponse.from_application(link, runtime(request).config.public_base_url)
                for link in result.items
            ],
            total=result.total,
        ),
        NavigationFacts(
            next_token=filters.next_token(actor, "links", result.page, result.has_next)
        ),
    )


@router.post("/links", response_model=LinkResponse, status_code=201, operation_id="create_link")
async def create_link(
    data: CreateLinkRequest,
    request: Request,
    response: Response,
    actor: Creator,
    _key: KeyHeader,
) -> LinkResponse:
    """Create an active link and replay its original result for retries of the same key."""
    result = await mutate(request, CreateLinkCommand(actor, data.draft()), actor)
    response.headers["Location"] = ApiContract.resource("links", result.id)
    return LinkResponse.from_application(result, runtime(request).config.public_base_url)


@router.get("/links/{link_id}", response_model=LinkResponse, operation_id="get_link")
async def get_link(link_id: str, request: Request, actor: Reader) -> LinkResponse:
    """Read one link belonging to the current organization."""
    result = await queries(request).ask(
        GetLinkQuery(actor, LinkId(link_id)), context=request_context(request, actor)
    )
    return LinkResponse.from_application(result, runtime(request).config.public_base_url)


@router.patch("/links/{link_id}", response_model=LinkResponse, operation_id="update_link")
async def update_link(
    link_id: str, data: UpdateLinkRequest, request: Request, actor: Updater, _key: KeyHeader
) -> LinkResponse:
    """Update a link. First activation atomically queues prior subscriptions."""
    result = await mutate(request, UpdateLinkCommand(actor, LinkId(link_id), data.patch()), actor)
    return LinkResponse.from_application(result, runtime(request).config.public_base_url)


@router.delete("/links/{link_id}", status_code=204, operation_id="delete_link")
async def delete_link(link_id: str, request: Request, actor: Deleter, _key: KeyHeader) -> None:
    """Delete a link and cancel waiting subscriptions. Repeated keys replay success."""
    await mutate(request, DeleteLinkCommand(actor, LinkId(link_id)), actor)


@router.post("/pools", response_model=PoolResponse, status_code=201, operation_id="reserve_pool")
async def reserve_pool(
    data: ReservePoolRequest,
    request: Request,
    response: Response,
    actor: Creator,
    _key: KeyHeader,
) -> PoolResponse:
    """Reserve 1–100 short links without destinations in one atomic pool."""
    pool = await mutate(request, ReservePoolCommand(actor, data.size, data.name), actor)
    response.headers["Location"] = f"{ApiContract.resource('links')}?pool_id={pool.id}"
    return PoolResponse.from_application(pool)


@router.get("/pools", operation_id="list_pools")
@linked(format="hal")
async def list_pools(
    request: Request, actor: Reader, pagination: Annotated[Pagination, Query()]
) -> LinkedResponse[PageResponse[PoolResponse]]:
    """List the current organization’s pools with bounded forward navigation."""
    result = await queries(request).ask(
        ListPoolsQuery(actor, pagination.page(actor, "pools"), pagination.limit),
        context=request_context(request, actor),
    )
    return LinkedResponse(
        PageResponse[PoolResponse](
            items=[PoolResponse.from_application(pool) for pool in result.items],
            total=result.total,
        ),
        NavigationFacts(
            next_token=pagination.next_token(actor, "pools", result.page, result.has_next)
        ),
    )
