from shared_messaging.invocation import Invocation

from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.application.commands.reserve_pool.command import ReservePoolCommand
from app.contexts.links.application.dto.links import PoolDto
from app.contexts.links.application.ports.repository import LinkRepository
from app.contexts.links.domain.link import LinkConflictError, LinkPolicy, PublicCode


class ReservePoolHandler:
    def __init__(self, repository: LinkRepository, access: OrganizationAccessPort) -> None:
        self._repository, self._access = repository, access

    async def execute(self, command: ReservePoolCommand, *, context: Invocation) -> PoolDto:
        organization = await self._access.require(command.actor, "links:create")
        policy = LinkPolicy.select(
            command.entropy,
            command.visibility,
            workload=command.actor.client_id in organization.workloads,
        )
        for _ in range(5):
            codes = tuple(PublicCode.generate(policy.entropy) for _ in range(command.size))
            if len(set(codes)) != command.size:
                continue
            try:
                pool = await self._repository.reserve(organization.id, command.name, codes, policy)
            except LinkConflictError:
                continue
            await self._repository.audit(organization.id, "reserve", (pool.id,), context)
            return pool
        raise LinkConflictError
