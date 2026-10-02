"""Core link use cases. Both JSON and HTML adapters enter through this boundary."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.contexts.access.contracts import Principal


class LinkNotFoundError(Exception):
    """No link is visible in the caller's workspace."""


class LinkConflictError(Exception):
    """The requested public code is already allocated."""


@dataclass(frozen=True)
class LinkDraft:
    destination_url: str
    title: str | None = None
    short_code: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class LinkPatch:
    fields: frozenset[str]
    destination_url: str | None = None
    title: str | None = None
    notes: str | None = None
    is_active: bool | None = None


@dataclass(frozen=True)
class LinkView:
    id: str
    short_code: str
    destination_url: str
    title: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class LinkPage:
    items: list[LinkView]
    total: int
    page: int
    page_size: int
    has_next: bool


class LinkRepository(Protocol):
    """Every operation is scoped to one already-authorized local workspace."""

    async def list(self, page: int, page_size: int) -> LinkPage: ...
    async def get(self, link_id: str) -> LinkView: ...
    async def create(self, draft: LinkDraft) -> LinkView: ...
    async def update(self, link_id: str, patch: LinkPatch) -> LinkView: ...
    async def delete(self, link_id: str) -> None: ...


class LinkManagement:
    def __init__(self, principal: Principal, repository: LinkRepository) -> None:
        self.principal = principal
        self._repository = repository

    async def list(self, page: int = 1, page_size: int = 20) -> LinkPage:
        self.principal.require("read:links")
        return await self._repository.list(page, page_size)

    async def get(self, link_id: str) -> LinkView:
        self.principal.require("read:links")
        return await self._repository.get(link_id)

    async def create(self, draft: LinkDraft) -> LinkView:
        self.principal.require("create:links")
        return await self._repository.create(draft)

    async def update(self, link_id: str, patch: LinkPatch) -> LinkView:
        self.principal.require("update:links")
        return await self._repository.update(link_id, patch)

    async def delete(self, link_id: str) -> None:
        self.principal.require("delete:links")
        await self._repository.delete(link_id)
