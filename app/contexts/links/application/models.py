"""Read models returned by the link application boundary."""

from dataclasses import dataclass
from datetime import datetime


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


@dataclass(frozen=True)
class ClickDraft:
    link_id: str
    ip: str
    user_agent: str | None
    referrer: str | None
    variant_id: str | None = None
