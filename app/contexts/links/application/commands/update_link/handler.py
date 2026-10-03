from time import perf_counter

from shared_messaging.invocation import Invocation
from shared_observability.telemetry import TelemetryService

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.commands.update_link.command import UpdateLinkCommand
from app.contexts.links.application.dto.links import LinkDto
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.application.telemetry.signals import ENQUEUE, ENQUEUE_DURATION
from app.contexts.links.domain.link import InvalidLinkError


class UpdateLinkHandler:
    def __init__(
        self,
        repository: LinkRepository,
        access: OrganizationAccessPort,
        telemetry: TelemetryService | None = None,
    ) -> None:
        self._repository, self._access = repository, access
        self._telemetry = telemetry

    async def execute(self, command: UpdateLinkCommand, *, context: Invocation) -> LinkDto:
        organization = await self._access.require(command.actor, "links:update")
        previous = await self._repository.get(organization.id, command.link_id, lock=True)
        activating = previous.destination_url is None and "destination_url" in command.patch.fields
        if activating and (
            command.patch.is_active is False
            or (not previous.is_active and command.patch.is_active is not True)
        ):
            raise InvalidLinkError("Enable a reserved link when assigning its destination")
        link = await self._repository.update(organization.id, command.link_id, command.patch)
        if activating:
            started = perf_counter()
            with ENQUEUE.start(self._telemetry, instrumentation_name=__name__):
                await self._repository.ready_subscriptions(organization.id, link.id, context)
            if self._telemetry is not None:
                self._telemetry.metrics.emit(ENQUEUE_DURATION, value=perf_counter() - started)
        await self._repository.audit(organization.id, "update", link.id, context)
        return link
