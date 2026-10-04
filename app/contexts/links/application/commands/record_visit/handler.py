from shared_messaging.invocation import Invocation

from app.contexts.links.application.commands.record_visit.command import RecordVisitCommand
from app.contexts.links.application.ports.repository import LinkRepository


class RecordVisitHandler:
    def __init__(self, repository: LinkRepository) -> None:
        self._repository = repository

    async def execute(self, command: RecordVisitCommand, *, context: Invocation) -> None:
        await self._repository.record_visit(command.link_id, command.code, command.outcome)
