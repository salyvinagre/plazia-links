from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Self

from app.contexts.links.application.dto.pixels import PixelDto
from app.contexts.links.application.dto.statistics import StatisticsDto
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


@dataclass(frozen=True, slots=True, kw_only=True)
class LinkReadDto(LinkDto):
    statistics: StatisticsDto

    @classmethod
    def from_application(cls, link: LinkDto, statistics: StatisticsDto) -> Self:
        return cls(
            id=link.id,
            short_code=link.short_code,
            destination_url=link.destination_url,
            title=link.title,
            notes=link.notes,
            is_active=link.is_active,
            created_at=link.created_at,
            updated_at=link.updated_at,
            pool_id=link.pool_id,
            statistics=statistics,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PoolReadDto(PoolDto):
    statistics: StatisticsDto

    @classmethod
    def from_application(cls, pool: PoolDto, statistics: StatisticsDto) -> Self:
        return cls(
            id=pool.id,
            name=pool.name,
            size=pool.size,
            created_at=pool.created_at,
            statistics=statistics,
        )


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
    value: LinkDto | PoolDto | PixelDto | None
    replayed: bool = False
