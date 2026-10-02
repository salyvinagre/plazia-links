from typing import Literal

from shared_messaging.invocation import Invocation

from app.contexts.links.application.commands.subscribe_link.command import SubscribeLinkCommand
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.domain.link import LinkDisabledError


class SubscribeLinkHandler:
    def __init__(self, repository: LinkRepository) -> None:
        self._repository = repository

    async def execute(
        self, command: SubscribeLinkCommand, *, context: Invocation
    ) -> Literal["waiting", "active"]:
        link = await self._repository.public(command.short_code, lock=True)
        if not link.is_active:
            raise LinkDisabledError
        if link.destination_url is not None:
            return "active"
        await self._repository.subscribe(link.id, command.email)
        return "waiting"
