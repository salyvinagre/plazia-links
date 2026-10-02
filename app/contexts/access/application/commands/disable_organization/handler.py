from shared_messaging.invocation import Invocation

from app.contexts.access.application.commands.disable_organization.command import (
    DisableOrganizationCommand,
)
from app.contexts.access.application.ports.organizations import OrganizationRepository


class DisableOrganizationHandler:
    def __init__(self, repository: OrganizationRepository) -> None:
        self._repository = repository

    async def execute(self, command: DisableOrganizationCommand, *, context: Invocation) -> None:
        await self._repository.disable(command.issuer, command.organization_id)
