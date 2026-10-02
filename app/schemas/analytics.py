from pydantic import BaseModel

from app.schemas.internal import (
    BrowserCount,
    CityCount,
    CountryCount,
    DateCount,
    DeviceCount,
    HourCount,
    OSCount,
    ReferrerCount,
    WorkspaceLinkSummary,
)


class ClickStats(BaseModel):
    total_clicks: int
    clicks_over_time: list[DateCount]
    top_referrers: list[ReferrerCount]
    browsers: list[BrowserCount]
    devices: list[DeviceCount]
    oss: list[OSCount]
    unique_clicks: int = 0
    top_countries: list[CountryCount] = []
    top_cities: list[CityCount] = []
    hourly_stats: list[HourCount] = []


class WorkspaceSummary(BaseModel):
    total_clicks: int
    total_links: int
    links: list[WorkspaceLinkSummary]
