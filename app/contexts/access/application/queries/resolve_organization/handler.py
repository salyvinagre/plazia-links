from shared_messaging.invocation import Invocation

from app.contexts.access.application.dto.organization import OrganizationDto
from app.contexts.access.application.policies.organization import OrganizationAccess
from app.contexts.access.application.queries.resolve_organization.query import (
    ResolveOrganizationQuery,
)


class ResolveOrganizationHandler:
    def __init__(self, access: OrganizationAccess) -> None:
        self._access = access

    async def execute(
        self, query: ResolveOrganizationQuery, *, context: Invocation | None
    ) -> OrganizationDto:
        return await self._access.resolve(query.actor)
