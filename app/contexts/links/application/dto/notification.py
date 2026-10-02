from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EmailJobDto:
    id: UUID
    email: str
    short_code: str
    attempts: int
    traceparent: str | None = None
    tracestate: str | None = None
