from shared_messaging.invocation import Invocation

from app.contexts.links.application.commands.record_pixel_request.command import (
    RecordPixelRequestCommand,
)
from app.contexts.links.application.ports.pixels import PixelRepository


class RecordPixelRequestHandler:
    def __init__(self, repository: PixelRepository) -> None:
        self._repository = repository

    async def execute(self, command: RecordPixelRequestCommand, *, context: Invocation) -> None:
        await self._repository.record(command.id, command.code)
