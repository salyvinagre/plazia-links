from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.kernel.ids import LinkId, PoolId


@dataclass(frozen=True, slots=True)
class LinkDto:
    id: LinkId
    short_code: str
    destination_url: str | None
    title: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    pool_id: PoolId | None = None

    @property
    def status(self) -> Literal["disabled", "reserved", "active"]:
        if not self.is_active:
            return "disabled"
        return "reserved" if self.destination_url is None else "active"


@dataclass(frozen=True, slots=True)
class PoolDto:
    id: PoolId
    name: str | None
    size: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PageDto[T]:
    items: tuple[T, ...]
    total: int
    page: int
    page_size: int

    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total


@dataclass(frozen=True, slots=True)
class PublicLinkDto:
    id: LinkId
    short_code: str
    destination_url: str | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class CommandResultDto:
    value: LinkDto | PoolDto | None
    replayed: bool = False
