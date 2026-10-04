"""JSON adapters dispatch CQRS intents; persistence never crosses this boundary."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from shared_http.fastapi import ApiErrorResponse, LinkedResponse, NavigationFacts, linked

from app.contexts.links.contracts import (
    CreateLinkCommand,
    DeleteLinkCommand,
    DeletePoolCommand,
    GetLinkQuery,
    GetPoolQuery,
    GetStatisticsQuery,
    ListLinksQuery,
    ListPoolsQuery,
    RenamePoolCommand,
    ReservePoolCommand,
    UpdateLinkCommand,
)
from app.interfaces.api.schemas.links import (
    CreateLinkRequest,
    DeleteLinksParams,
    LinkFilter,
    LinkIdText,
    LinkReadResponse,
    LinkResponse,
    PageResponse,
    Pagination,
    PoolIdText,
    PoolReadResponse,
    PoolResponse,
    RenamePoolRequest,
    ReservePoolRequest,
    StatisticsResponse,
    UpdateLinkRequest,
)
from app.interfaces.authentication import Creator, Deleter, KeyHeader, Reader, Updater, runtime
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


@router.get("/links", operation_id="list_links")
@linked(format="hal")
async def list_links(
    request: Request, actor: Reader, filters: Annotated[LinkFilter, Query()]
) -> LinkedResponse[PageResponse[LinkReadResponse]]:
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
        PageResponse[LinkReadResponse](
            items=[
                LinkReadResponse.from_read(link, runtime(request).config.public_base_url)
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


@router.delete("/links", status_code=204, operation_id="delete_links")
async def delete_links(
    request: Request,
    actor: Deleter,
    filters: Annotated[DeleteLinksParams, Query()],
    _key: KeyHeader,
) -> None:
    """Delete explicit links or all matching links across pages, preserving their pools."""
    await mutate(request, filters.command(actor), actor)


@router.get("/links/{link_id}", response_model=LinkReadResponse, operation_id="get_link")
async def get_link(
    link_id: Annotated[LinkIdText, Path(description="Canonical link identifier.")],
    request: Request,
    actor: Reader,
) -> LinkReadResponse:
    """Read one link belonging to the current organization."""
    result = await queries(request).ask(
        GetLinkQuery(actor, LinkId(link_id)), context=request_context(request, actor)
    )
    return LinkReadResponse.from_read(result, runtime(request).config.public_base_url)


@router.patch("/links/{link_id}", response_model=LinkResponse, operation_id="update_link")
async def update_link(
    link_id: Annotated[LinkIdText, Path(description="Canonical link identifier.")],
    data: UpdateLinkRequest,
    request: Request,
    actor: Updater,
    _key: KeyHeader,
) -> LinkResponse:
    """Update a link. First activation atomically queues prior subscriptions."""
    result = await mutate(request, UpdateLinkCommand(actor, LinkId(link_id), data.patch()), actor)
    return LinkResponse.from_application(result, runtime(request).config.public_base_url)


@router.delete("/links/{link_id}", status_code=204, operation_id="delete_link")
async def delete_link(
    link_id: Annotated[LinkIdText, Path(description="Canonical link identifier.")],
    request: Request,
    actor: Deleter,
    _key: KeyHeader,
) -> None:
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
    response.headers["Location"] = ApiContract.resource("pools", pool.id)
    return PoolResponse.from_application(pool)


@router.get("/pools", operation_id="list_pools")
@linked(format="hal")
async def list_pools(
    request: Request, actor: Reader, pagination: Annotated[Pagination, Query()]
) -> LinkedResponse[PageResponse[PoolReadResponse]]:
    """List the current organization’s pools with bounded forward navigation."""
    result = await queries(request).ask(
        ListPoolsQuery(actor, pagination.page(actor, "pools"), pagination.limit),
        context=request_context(request, actor),
    )
    return LinkedResponse(
        PageResponse[PoolReadResponse](
            items=[PoolReadResponse.from_read(pool) for pool in result.items],
            total=result.total,
        ),
        NavigationFacts(
            next_token=pagination.next_token(actor, "pools", result.page, result.has_next)
        ),
    )


@router.get("/pools/{pool_id}", response_model=PoolReadResponse, operation_id="get_pool")
async def get_pool(
    pool_id: Annotated[PoolIdText, Path(description="Canonical pool identifier.")],
    request: Request,
    actor: Reader,
) -> PoolReadResponse:
    """Read one pool and its current number of links in the verified organization."""
    pool = await queries(request).ask(
        GetPoolQuery(actor, PoolId(pool_id)), context=request_context(request, actor)
    )
    return PoolReadResponse.from_read(pool)


@router.get("/statistics", response_model=StatisticsResponse, operation_id="get_statistics")
async def get_statistics(request: Request, actor: Reader) -> StatisticsResponse:
    """Read request totals across all current organization links, independent of pagination."""
    statistics = await queries(request).ask(
        GetStatisticsQuery(actor), context=request_context(request, actor)
    )
    return StatisticsResponse.from_application(statistics)


@router.patch("/pools/{pool_id}", response_model=PoolResponse, operation_id="rename_pool")
async def rename_pool(
    pool_id: Annotated[PoolIdText, Path(description="Canonical pool identifier.")],
    data: RenamePoolRequest,
    request: Request,
    actor: Updater,
    _key: KeyHeader,
) -> PoolResponse:
    """Rename a pool without changing its links. Repeated keys replay the original name."""
    pool = await mutate(request, RenamePoolCommand(actor, PoolId(pool_id), data.name), actor)
    return PoolResponse.from_application(pool)


@router.delete("/pools/{pool_id}", status_code=204, operation_id="delete_pool")
async def delete_pool(
    pool_id: Annotated[PoolIdText, Path(description="Canonical pool identifier.")],
    request: Request,
    actor: Deleter,
    _key: KeyHeader,
) -> None:
    """Delete a pool, all its links, subscriptions and queued activation emails atomically."""
    await mutate(request, DeletePoolCommand(actor, PoolId(pool_id)), actor)
