from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.dto.links import PageDto, PoolDto
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.application.queries.list_pools.query import ListPoolsQuery


class ListPoolsHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(
        self, query: ListPoolsQuery, *, context: Invocation | None
    ) -> PageDto[PoolDto]:
        organization = await self._access.require(query.actor, "links:read")
        return await self._repository.pools(organization.id, query.page, query.page_size)
