from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.dto.statistics import StatisticsDto
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.application.queries.get_statistics.query import GetStatisticsQuery


class GetStatisticsHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(
        self, query: GetStatisticsQuery, *, context: Invocation | None
    ) -> StatisticsDto:
        organization = await self._access.require(query.actor, "links:read")
        return (await self._repository.statistics(organization.id, (organization.id,)))[
            organization.id
        ]
