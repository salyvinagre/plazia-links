from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.dto.links import LinkDto
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.application.queries.get_link.query import GetLinkQuery


class GetLinkHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(self, query: GetLinkQuery, *, context: Invocation | None) -> LinkDto:
        organization = await self._access.require(query.actor, "links:read")
        return await self._repository.get(organization.id, query.link_id)
