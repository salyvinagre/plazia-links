from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.commands.rename_pool.command import RenamePoolCommand
from app.contexts.links.application.dto.links import PoolDto
from app.contexts.links.application.ports.repository import LinkRepository


class RenamePoolHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(self, command: RenamePoolCommand, *, context: Invocation) -> PoolDto:
        organization = await self._access.require(command.actor, "links:update")
        pool = await self._repository.rename_pool(organization.id, command.pool_id, command.name)
        await self._repository.audit(organization.id, "rename", pool.id, context)
        return pool
