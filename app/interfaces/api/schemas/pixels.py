from typing import Annotated, Self

from pydantic import AfterValidator, AwareDatetime, Field
from shared_http.fastapi import ApiRequest, ApiResponse

from app.contexts.links.contracts import PixelDraft, PixelDto, PixelReadDto, PixelStatisticsDto
from app.kernel.ids import PixelId

PixelIdText = Annotated[
    str,
    AfterValidator(PixelId.normalize),
    Field(min_length=36, max_length=36, description="Canonical pixel identifier."),
]


class CreatePixelRequest(ApiRequest):
    reference: str | None = Field(
        None,
        max_length=200,
        description="Optional sender-owned delivery reference; use no email address.",
    )

    def draft(self) -> PixelDraft:
        return PixelDraft(self.reference)


class PixelResponse(ApiResponse):
    id: PixelIdText
    reference: str | None = Field(
        max_length=200, description="Delivery reference; null when unset."
    )
    image_url: str = Field(description="Stable public URL of a transparent 1×1 GIF.")
    created_at: AwareDatetime = Field(description="Creation and collection start in UTC.")

    @classmethod
    def from_application(cls, pixel: PixelDto, public_base: str) -> Self:
        return cls(
            id=str(pixel.id),
            reference=pixel.reference,
            image_url=f"{public_base.rstrip('/')}/pixels/{pixel.code}.gif",
            created_at=pixel.created_at,
        )


class PixelStatisticsResponse(ApiResponse):
    requests: int = Field(
        ge=0, description="Best-effort image GET requests, including repeats and automation."
    )
    first_requested_at: AwareDatetime | None = Field(
        description="First recorded request in UTC; null before any."
    )
    last_requested_at: AwareDatetime | None = Field(
        description="Latest recorded request in UTC; null before any."
    )
    as_of: AwareDatetime = Field(description="Statistics read time in UTC.")

    @classmethod
    def from_application(cls, statistics: PixelStatisticsDto) -> Self:
        return cls.model_validate(statistics, from_attributes=True)


class PixelReadResponse(PixelResponse):
    statistics: PixelStatisticsResponse = Field(
        description="Image fetches, not confirmed human reads."
    )

    @classmethod
    def from_read(cls, pixel: PixelReadDto, public_base: str) -> Self:
        return cls(
            **PixelResponse.from_application(pixel, public_base).model_dump(exclude_none=False),
            statistics=PixelStatisticsResponse.from_application(pixel.statistics),
        )
