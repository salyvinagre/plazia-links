from dataclasses import replace

from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.commands.create_link.command import CreateLinkCommand
from app.contexts.links.application.dto.links import LinkDto
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.domain.link import LinkConflictError, PublicCode


class CreateLinkHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(self, command: CreateLinkCommand, *, context: Invocation) -> LinkDto:
        organization = await self._access.require(command.actor, "links:create")
        for _ in range(5):
            draft = (
                command.draft
                if command.draft.short_code
                else replace(command.draft, short_code=PublicCode.generate())
            )
            try:
                link = await self._repository.create(organization.id, draft)
            except LinkConflictError:
                if command.draft.short_code:
                    raise
                continue
            await self._repository.audit(organization.id, "create", link.id, context)
            return link
        raise LinkConflictError
