from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from shared_kernel.fields import AnnotatedFields, DateTimeCoerce, IntValue, Minimum

from app.kernel.ids import PixelId


@dataclass(frozen=True, slots=True)
class PixelDto:
    id: PixelId
    code: str
    reference: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PixelStatisticsDto:
    requests: Annotated[int, IntValue(), Minimum(0)]
    first_requested_at: Annotated[datetime | None, DateTimeCoerce()]
    last_requested_at: Annotated[datetime | None, DateTimeCoerce()]
    as_of: Annotated[datetime, DateTimeCoerce()]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class PixelReadDto(PixelDto):
    statistics: PixelStatisticsDto
