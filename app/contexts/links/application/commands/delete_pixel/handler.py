from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.commands.delete_pixel.command import DeletePixelCommand
from app.contexts.links.application.ports.pixels import PixelRepository
from app.contexts.links.application.ports.repository import LinkRepository


class DeletePixelHandler:
    def __init__(
        self, repository: PixelRepository, access: OrganizationAccessPort, audit: LinkRepository
    ) -> None:
        self._repository, self._access, self._audit = repository, access, audit

    async def execute(self, command: DeletePixelCommand, *, context: Invocation) -> None:
        organization = await self._access.require(command.actor, "links:delete")
        await self._repository.delete(organization.id, command.id)
        await self._audit.audit(organization.id, "delete", (command.id,), context)
