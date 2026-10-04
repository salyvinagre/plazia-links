from shared_messaging.invocation import Invocation

from app.contexts.links.application.ports.pixels import PixelRepository
from app.contexts.links.application.queries.resolve_pixel.query import ResolvePixelQuery
from app.kernel.ids import PixelId


class ResolvePixelHandler:
    def __init__(self, repository: PixelRepository) -> None:
        self._repository = repository

    async def execute(self, query: ResolvePixelQuery, *, context: Invocation | None) -> PixelId:
        return await self._repository.public(query.code)
