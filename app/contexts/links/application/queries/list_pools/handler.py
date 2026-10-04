from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.dto.links import PageDto, PoolReadDto
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.application.queries.list_pools.query import ListPoolsQuery


class ListPoolsHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(
        self, query: ListPoolsQuery, *, context: Invocation | None
    ) -> PageDto[PoolReadDto]:
        organization = await self._access.require(query.actor, "links:read")
        page = await self._repository.pools(organization.id, query.page, query.page_size)
        statistics = await self._repository.statistics(
            organization.id, tuple(pool.id for pool in page.items)
        )
        return PageDto(
            tuple(PoolReadDto.from_application(pool, statistics[pool.id]) for pool in page.items),
            page.total,
            page.page,
            page.page_size,
        )
