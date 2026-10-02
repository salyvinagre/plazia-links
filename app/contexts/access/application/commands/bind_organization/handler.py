from shared_messaging.invocation import Invocation

from app.contexts.access.application.commands.bind_organization.command import (
    BindOrganizationCommand,
)
from app.contexts.access.application.ports.organizations import OrganizationRepository


class BindOrganizationHandler:
    def __init__(self, repository: OrganizationRepository) -> None:
        self._repository = repository

    async def execute(self, command: BindOrganizationCommand, *, context: Invocation) -> None:
        await self._repository.bind(command.issuer, command.organization_id, command.name)
