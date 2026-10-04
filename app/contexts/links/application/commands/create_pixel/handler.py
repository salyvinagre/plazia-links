from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.commands.create_pixel.command import CreatePixelCommand
from app.contexts.links.application.dto.pixels import PixelDto
from app.contexts.links.application.ports.pixels import PixelRepository
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.domain.pixel import PixelCode, PixelConflictError


class CreatePixelHandler:
    def __init__(
        self, repository: PixelRepository, access: OrganizationAccessPort, audit: LinkRepository
    ) -> None:
        self._repository, self._access, self._audit = repository, access, audit

    async def execute(self, command: CreatePixelCommand, *, context: Invocation) -> PixelDto:
        organization = await self._access.require(command.actor, "links:create")
        for _ in range(5):
            try:
                pixel = await self._repository.create(
                    organization.id, command.draft, PixelCode.generate()
                )
            except PixelConflictError:
                continue
            await self._audit.audit(organization.id, "create", (pixel.id,), context)
            return pixel
        raise PixelConflictError
