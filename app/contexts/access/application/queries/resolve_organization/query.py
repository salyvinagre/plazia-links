from dataclasses import dataclass

from app.contexts.access.domain.principal import Principal


@dataclass(frozen=True, slots=True)
class ResolveOrganizationQuery:
    actor: Principal
