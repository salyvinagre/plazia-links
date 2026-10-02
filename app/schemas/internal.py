"""Typed service records shared with API serializers.

These describe existing payloads; they are not ORM entities or a new API envelope.
"""

from typing import NotRequired, TypedDict


class SessionInfo(TypedDict):
    jti: str
    ip: str
    user_agent: str
    created_at: str
    is_current: NotRequired[bool]


class GeoLocation(TypedDict):
    country: str | None
    city: str | None
    latitude: float | None
    longitude: float | None


class DateCount(TypedDict):
    date: str
    count: int


class DateClicks(TypedDict):
    date: str
    clicks: int


class ReferrerCount(TypedDict):
    domain: str
    count: int


class BrowserCount(TypedDict):
    browser: str
    count: int


class DeviceCount(TypedDict):
    device: str
    count: int


class OSCount(TypedDict):
    os: str
    count: int


class CountryCount(TypedDict):
    country: str
    count: int


class CityCount(TypedDict):
    city: str
    country: str | None
    count: int


class HourCount(TypedDict):
    hour: str
    count: int


class WorkspaceLinkSummary(TypedDict):
    id: str
    short_code: str
    destination_url: str
    title: str | None
    clicks: int


class WorkspaceSummaryData(TypedDict):
    total_clicks: int
    total_links: int
    links: list[WorkspaceLinkSummary]


class ExpiryNotice(TypedDict):
    event: str
    link_id: str
    short_code: str
    title: str | None
    destination_url: str
    expires_at: str


class BulkImportError(TypedDict):
    row: int
    error: str


class BulkImportResult(TypedDict):
    created: int
    errors: list[BulkImportError]


class EmailSendResult(TypedDict):
    status: str
    to: list[str]
    error: NotRequired[str]
