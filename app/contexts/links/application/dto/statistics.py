from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from shared_kernel.fields import AnnotatedFields, DateTimeCoerce, IntValue, Minimum

VisitOutcome = Literal["redirect", "waiting"]


@dataclass(frozen=True, slots=True)
class StatisticsDto:
    redirects: Annotated[int, IntValue(), Minimum(0)]
    waiting_views: Annotated[int, IntValue(), Minimum(0)]
    subscribers: Annotated[int, IntValue(), Minimum(0)]
    last_visited_at: Annotated[datetime | None, DateTimeCoerce()]
    tracked_from: Annotated[datetime, DateTimeCoerce()]
    as_of: Annotated[datetime, DateTimeCoerce()]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
