from typing import Protocol

from shared_identity.canonical_ids import OrganizationId

from app.contexts.access.application.dto.organization import OrganizationDto
from app.contexts.access.domain.principal import Permission, Principal


class OrganizationAccessPort(Protocol):
    async def require(self, principal: Principal, permission: Permission) -> OrganizationDto: ...
    async def resolve(self, principal: Principal) -> OrganizationDto: ...


class OrganizationRepository(Protocol):
    async def find(
        self, issuer: str, organization_id: OrganizationId
    ) -> OrganizationDto | None: ...
    async def bind(self, issuer: str, organization_id: OrganizationId, name: str) -> None: ...
    async def disable(self, issuer: str, organization_id: OrganizationId) -> None: ...
