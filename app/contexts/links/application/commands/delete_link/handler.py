from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.commands.delete_link.command import DeleteLinkCommand
from app.contexts.links.application.ports.repository import LinkRepository


class DeleteLinkHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(self, command: DeleteLinkCommand, *, context: Invocation) -> None:
        organization = await self._access.require(command.actor, "links:delete")
        await self._repository.delete(organization.id, command.link_id)
        await self._repository.audit(organization.id, "delete", (command.link_id,), context)
