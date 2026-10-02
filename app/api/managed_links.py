"""JSON adapter. Authentication never falls back to a browser cookie or local key."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.access.contracts import Principal
from app.contexts.links.application.management import LinkView
from app.core.dependencies import get_db
from app.core.identity import api_principal, runtime
from app.platform.access import link_management
from app.schemas.managed_link import (
    CreateLinkRequest,
    ManagedLinkPage,
    ManagedLinkResponse,
    UpdateLinkRequest,
)

router = APIRouter(prefix="/api/v1/links", tags=["links"])
Db = Annotated[AsyncSession, Depends(get_db)]
Actor = Annotated[Principal, Depends(api_principal)]


def _response(link: LinkView, request: Request) -> ManagedLinkResponse:
    return ManagedLinkResponse(
        id=link.id,
        short_code=link.short_code,
        short_url=f"{runtime(request).config.public_base_url.rstrip('/')}/{link.short_code}",
        destination_url=link.destination_url,
        title=link.title,
        notes=link.notes,
        is_active=link.is_active,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


@router.get("", response_model=ManagedLinkPage, operation_id="listLinks")
async def list_links(
    request: Request,
    db: Db,
    actor: Actor,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ManagedLinkPage:
    result = await (await link_management(db, actor)).list(page, page_size)
    return ManagedLinkPage(
        items=[_response(item, request) for item in result.items],
        total=result.total,
        page=page,
        page_size=page_size,
        has_next=result.has_next,
    )


@router.post("", response_model=ManagedLinkResponse, status_code=201, operation_id="createLink")
async def create_link(
    data: CreateLinkRequest, request: Request, response: Response, db: Db, actor: Actor
) -> ManagedLinkResponse:
    link = await (await link_management(db, actor)).create(data.draft())
    response.headers["Location"] = f"/api/v1/links/{link.id}"
    return _response(link, request)


@router.get("/{link_id}", response_model=ManagedLinkResponse, operation_id="getLink")
async def get_link(link_id: str, request: Request, db: Db, actor: Actor) -> ManagedLinkResponse:
    return _response(await (await link_management(db, actor)).get(link_id), request)


@router.patch("/{link_id}", response_model=ManagedLinkResponse, operation_id="updateLink")
async def update_link(
    link_id: str, data: UpdateLinkRequest, request: Request, db: Db, actor: Actor
) -> ManagedLinkResponse:
    return _response(
        await (await link_management(db, actor)).update(link_id, data.patch()), request
    )


@router.delete("/{link_id}", status_code=204, operation_id="deleteLink")
async def delete_link(link_id: str, db: Db, actor: Actor) -> None:
    await (await link_management(db, actor)).delete(link_id)


# OAuth2 scopes are enforced by LinkManagement, not inferred from token roles.
_scope_by_method = {
    "GET": "read:links",
    "POST": "create:links",
    "PATCH": "update:links",
    "DELETE": "delete:links",
}

for _route in router.routes:
    if isinstance(_route, APIRoute) and _route.methods:
        _method = next(iter(_route.methods))
        _route.openapi_extra = {
            "security": [{"IdentityAccess": [_scope_by_method[_method]]}],
            "parameters": [
                {
                    "name": "DPoP",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "RFC 9449 proof; mandatory with DPoP-bound tokens.",
                }
            ],
        }
