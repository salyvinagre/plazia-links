from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.dto.links import PoolDto
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.application.queries.get_pool.query import GetPoolQuery


class GetPoolHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(self, query: GetPoolQuery, *, context: Invocation | None) -> PoolDto:
        organization = await self._access.require(query.actor, "links:read")
        return await self._repository.get_pool(organization.id, query.pool_id)
