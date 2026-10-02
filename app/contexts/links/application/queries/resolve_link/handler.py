from shared_messaging.invocation import Invocation

from app.contexts.links.application.dto.links import PublicLinkDto
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.application.queries.resolve_link.query import ResolveLinkQuery


class ResolveLinkHandler:
    def __init__(self, repository: LinkRepository) -> None:
        self._repository = repository

    async def execute(
        self, query: ResolveLinkQuery, *, context: Invocation | None
    ) -> PublicLinkDto:
        return await self._repository.public(query.short_code)
