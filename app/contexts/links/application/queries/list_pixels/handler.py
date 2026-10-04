from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.dto.links import PageDto
from app.contexts.links.application.dto.pixels import PixelReadDto
from app.contexts.links.application.ports.pixels import PixelRepository
from app.contexts.links.application.queries.list_pixels.query import ListPixelsQuery


class ListPixelsHandler:
    def __init__(self, repository: PixelRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(
        self, query: ListPixelsQuery, *, context: Invocation | None
    ) -> PageDto[PixelReadDto]:
        organization = await self._access.require(query.actor, "links:read")
        return await self._repository.list(organization.id, query.page, query.page_size)
