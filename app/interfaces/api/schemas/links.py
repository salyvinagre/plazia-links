from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)
from shared_http import PageTokenBinding, PageTokenCodec, PageTokenError
from shared_http.fastapi import ApiRequest, ApiResponse

from app.contexts.access.contracts import Principal
from app.contexts.links.contracts import (
    DeleteLinksCommand,
    Destination,
    LinkDraft,
    LinkDto,
    LinkPatch,
    PoolDto,
    PublicCode,
)
from app.kernel.ids import LinkId, PoolId

LinkIdText = Annotated[
    str,
    AfterValidator(LinkId.normalize),
    Field(min_length=36, max_length=36, description="Canonical link identifier."),
]
PoolIdText = Annotated[
    str,
    AfterValidator(PoolId.normalize),
    Field(min_length=36, max_length=36, description="Canonical pool identifier."),
]


class SubscriptionForm(ApiRequest):
    email: EmailStr = Field(max_length=320, description="Address for one activation notification.")


class CreateLinkRequest(ApiRequest):
    """Create an active link with optional owner metadata and a chosen short code."""

    destination_url: str = Field(
        min_length=1, max_length=8192, description="Public absolute HTTP(S) destination."
    )
    title: str | None = Field(None, max_length=200, description="Optional display title.")
    short_code: str | None = Field(
        None, min_length=3, max_length=10, description="Chosen short code; omit to generate one."
    )
    notes: str | None = Field(None, max_length=4000, description="Optional owner notes.")

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
    """Patch supplied fields. Destination and enabled state cannot be null."""

    destination_url: str | None = Field(
        None, min_length=1, max_length=8192, description="New destination; cannot be cleared."
    )
    title: str | None = Field(None, max_length=200, description="Optional display title.")
    notes: str | None = Field(None, max_length=4000, description="Optional owner notes.")
    is_active: bool | None = Field(None, strict=True, description="Enable or disable the link.")

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
    """Reserve a bounded set of unassigned links in the verified organization."""

    size: int = Field(ge=1, le=100, strict=True, description="Number of links to reserve.")
    name: str | None = Field(None, max_length=200, description="Optional display name.")


class RenamePoolRequest(ApiRequest):
    """Change pool metadata without changing its links."""

    name: str | None = Field(..., max_length=200, description="New display name; null clears it.")


class DeleteLinksParams(ApiRequest):
    ids: list[LinkIdText] | None = Field(
        None, min_length=1, max_length=100, description="Explicit links to delete; omit for all."
    )
    pool_id: PoolIdText | None = Field(
        None, description="Restrict every selected link to this pool."
    )
    all: bool = Field(False, description="Delete all matching links across pages; omit ids.")

    def command(self, actor: Principal) -> DeleteLinksCommand:
        return DeleteLinksCommand(
            actor,
            tuple(LinkId(value) for value in self.ids or ()),
            PoolId(self.pool_id) if self.pool_id else None,
            self.all,
        )


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
    pool_id: PoolIdText | None = Field(None, description="Restrict links to this pool.")


class LinkResponse(ApiResponse):
    """A short link visible to the verified organization."""

    id: LinkIdText
    short_code: str = Field(min_length=3, max_length=10, description="Stable public short code.")
    short_url: str = Field(description="Absolute public URL of this short link.")
    destination_url: str | None = Field(description="Destination URL; null while reserved.")
    title: str | None = Field(max_length=200, description="Display title; null when unset.")
    notes: str | None = Field(max_length=4000, description="Owner notes; null when unset.")
    is_active: bool = Field(description="Whether public access is enabled.")
    status: Literal["active", "reserved", "disabled"] = Field(description="Current public state.")
    pool_id: PoolIdText | None = Field(description="Owning pool; null for standalone links.")
    created_at: AwareDatetime = Field(description="Creation time in UTC.")
    updated_at: AwareDatetime = Field(description="Last modification time in UTC.")

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
    """Pool metadata and its current link count."""

    id: PoolIdText
    name: str | None = Field(max_length=200, description="Display name; null when unset.")
    size: int = Field(ge=0, le=100, description="Number of links currently in the pool.")
    created_at: AwareDatetime = Field(description="Reservation time in UTC.")

    @classmethod
    def from_application(cls, pool: PoolDto) -> PoolResponse:
        return cls(id=str(pool.id), name=pool.name, size=pool.size, created_at=pool.created_at)


class PageResponse[T](ApiResponse):
    """A bounded resource page; follow its shared HAL continuation links."""

    items: list[T] = Field(min_length=0, max_length=100, description="This page of resources.")
    total: int = Field(ge=0, description="Total resources matching the filter.")
