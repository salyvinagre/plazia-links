from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from shared_http import PageTokenBinding, PageTokenCodec, PageTokenError
from shared_http.fastapi import ApiRequest, ApiResponse

from app.contexts.access.contracts import Principal
from app.contexts.links.contracts import (
    Destination,
    LinkDraft,
    LinkDto,
    LinkPatch,
    PoolDto,
    PublicCode,
)
from app.kernel.ids import LinkId


class CreateLinkRequest(ApiRequest):
    destination_url: str = Field(min_length=1, max_length=8192)
    title: str | None = Field(None, max_length=200)
    short_code: str | None = Field(None, min_length=3, max_length=10)
    notes: str | None = Field(None, max_length=4000)

    @field_validator("destination_url")
    @classmethod
    def destination(cls, value: str) -> str:
        return Destination(value).value

    @field_validator("short_code")
    @classmethod
    def code(cls, value: str | None) -> str | None:
        return PublicCode(value).value if value is not None else None

    def draft(self) -> LinkDraft:
        return LinkDraft(self.destination_url, self.title, self.short_code, self.notes)


class UpdateLinkRequest(ApiRequest):
    destination_url: str | None = Field(None, min_length=1, max_length=8192)
    title: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=4000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def supplied(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        for field in ("destination_url", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if self.destination_url is not None:
            Destination(self.destination_url)
        return self

    def patch(self) -> LinkPatch:
        return LinkPatch(
            frozenset(self.model_fields_set),
            self.destination_url,
            self.title,
            self.notes,
            self.is_active,
        )


class ReservePoolRequest(ApiRequest):
    size: int = Field(ge=1, le=100, strict=True)
    name: str | None = Field(None, max_length=200)


class RenamePoolRequest(ApiRequest):
    name: str | None = Field(..., max_length=200, description="New display name; null clears it.")


class DeleteLinksParams(ApiRequest):
    ids: list[str] = Field(min_length=1, max_length=100, description="Explicit links to delete.")
    pool_id: str | None = Field(None, description="Restrict every selected link to this pool.")

    def identifiers(self) -> tuple[LinkId, ...]:
        return tuple(LinkId(value) for value in self.ids)


class Pagination(ApiRequest):
    limit: int = Field(20, ge=1, le=100, description="Maximum items to return.")
    token: str | None = Field(
        None, min_length=1, max_length=4096, description="Opaque continuation."
    )

    def bindings(self, actor: Principal) -> dict[str, PageTokenBinding]:
        return {
            "issuer": actor.issuer,
            "organization": str(actor.organization_id),
            "subject": actor.subject,
            "limit": self.limit,
            "pool": getattr(self, "pool_id", None),
        }

    def page(self, actor: Principal, resource: str) -> int:
        if self.token is None:
            return 1
        position = PageTokenCodec.decode(
            self.token, kind=resource, bindings=self.bindings(actor), position_count=1
        )[0]
        if not position.isascii() or not position.isdecimal() or not 1 <= int(position) <= 100000:
            raise PageTokenError("Invalid continuation position")
        return int(position)

    def next_token(self, actor: Principal, resource: str, page: int, has_next: bool) -> str | None:
        return (
            PageTokenCodec.encode(
                kind=resource, bindings=self.bindings(actor), position=(page + 1,)
            )
            if has_next
            else None
        )


class LinkFilter(Pagination):
    pool_id: str | None = None


class LinkResponse(ApiResponse):
    id: str
    short_code: str
    short_url: str
    destination_url: str | None
    title: str | None
    notes: str | None
    is_active: bool
    status: Literal["active", "reserved", "disabled"]
    pool_id: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_application(cls, link: LinkDto, public_base: str) -> LinkResponse:
        return cls(
            id=str(link.id),
            short_code=link.short_code,
            short_url=f"{public_base.rstrip('/')}/{link.short_code}",
            destination_url=link.destination_url,
            title=link.title,
            notes=link.notes,
            is_active=link.is_active,
            status=link.status,
            pool_id=str(link.pool_id) if link.pool_id else None,
            created_at=link.created_at,
            updated_at=link.updated_at,
        )


class PoolResponse(ApiResponse):
    id: str
    name: str | None
    size: int
    created_at: datetime

    @classmethod
    def from_application(cls, pool: PoolDto) -> PoolResponse:
        return cls(id=str(pool.id), name=pool.name, size=pool.size, created_at=pool.created_at)


class PageResponse[T](ApiResponse):
    items: list[T]
    total: int
