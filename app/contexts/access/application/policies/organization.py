from app.contexts.access.application.dto.organization import OrganizationDto
from app.contexts.access.application.ports.organizations import OrganizationRepository
from app.contexts.access.domain.principal import AccessDeniedError, Permission, Principal


class OrganizationAccess:
    def __init__(self, repository: OrganizationRepository) -> None:
        self._repository = repository

    async def require(self, principal: Principal, permission: Permission) -> OrganizationDto:
        principal.require(permission)
        return await self.resolve(principal)

    async def resolve(self, principal: Principal) -> OrganizationDto:
        binding = await self._repository.find(principal.issuer, principal.organization_id)
        if binding is None or not binding.is_active:
            raise AccessDeniedError("unbound_organization")
        return binding
