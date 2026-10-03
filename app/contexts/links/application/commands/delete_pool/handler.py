from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.commands.delete_pool.command import DeletePoolCommand
from app.contexts.links.application.ports.repository import LinkRepository


class DeletePoolHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(self, command: DeletePoolCommand, *, context: Invocation) -> None:
        organization = await self._access.require(command.actor, "links:delete")
        await self._repository.delete_pool(organization.id, command.pool_id)
        await self._repository.audit(organization.id, "delete", (command.pool_id,), context)
