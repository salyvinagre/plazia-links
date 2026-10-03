from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.commands.delete_links.command import DeleteLinksCommand
from app.contexts.links.application.ports.repository import LinkRepository


class DeleteLinksHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(self, command: DeleteLinksCommand, *, context: Invocation) -> None:
        organization = await self._access.require(command.actor, "links:delete")
        ids = await self._repository.delete_many(
            organization.id, command.ids, command.pool_id, all=command.all
        )
        await self._repository.audit(organization.id, "delete", ids, context)
