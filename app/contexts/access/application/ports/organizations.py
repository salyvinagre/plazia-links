from typing import Protocol

from shared_identity.canonical_ids import OrganizationId

from app.contexts.access.application.dto.organization import OrganizationDto


class OrganizationRepository(Protocol):
    async def find(
        self, issuer: str, organization_id: OrganizationId
    ) -> OrganizationDto | None: ...
    async def bind(self, issuer: str, organization_id: OrganizationId, name: str) -> None: ...
    async def disable(self, issuer: str, organization_id: OrganizationId) -> None: ...
