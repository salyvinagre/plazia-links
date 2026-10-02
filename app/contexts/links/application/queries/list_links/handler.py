from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.dto.links import LinkDto, PageDto
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.application.queries.list_links.query import ListLinksQuery


class ListLinksHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(
        self, query: ListLinksQuery, *, context: Invocation | None
    ) -> PageDto[LinkDto]:
        organization = await self._access.require(query.actor, "links:read")
        if query.pool_id is not None:
            await self._repository.get_pool(organization.id, query.pool_id)
        return await self._repository.list(
            organization.id, query.page, query.page_size, query.pool_id
        )
