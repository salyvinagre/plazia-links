from dataclasses import dataclass

from app.contexts.access.contracts import Principal


@dataclass(frozen=True, slots=True)
class GetStatisticsQuery:
    actor: Principal
