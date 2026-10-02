"""Organization binding policy and operator commands, independent of SQL and HTTP."""

from app.contexts.access.application.models import WorkspaceView
from app.contexts.access.application.ports import WorkspaceBindings
from app.contexts.access.domain.organization import OrganizationId
from app.contexts.access.domain.principal import AccessDeniedError, Principal


class WorkspaceAccess:
    def __init__(self, bindings: WorkspaceBindings) -> None:
        self._bindings = bindings

    async def resolve(self, principal: Principal) -> WorkspaceView:
        binding = await self._bindings.find(principal.issuer, principal.organization_id)
        if binding is None or not binding.active:
            raise AccessDeniedError("unbound_organization")
        return binding.workspace


class WorkspaceProvisioning:
    def __init__(self, bindings: WorkspaceBindings, issuer: str) -> None:
        self._bindings = bindings
        self._issuer = issuer

    async def bind(self, organization: str, name: str, workspace_id: str | None = None) -> str:
        organization = OrganizationId(organization).value
        name = name.strip()
        if not 1 <= len(name) <= 100:
            raise ValueError("Workspace name must contain 1–100 characters")
        existing = await self._bindings.find(self._issuer, organization)
        if existing is not None:
            if workspace_id is not None and existing.workspace.id != workspace_id:
                raise ValueError("Organization is already bound to a different workspace")
            await self._bindings.set_active(self._issuer, organization, True)
            return existing.workspace.id
        if workspace_id is None:
            workspace_id = await self._bindings.create_workspace(name)
        else:
            if not await self._bindings.workspace_exists(workspace_id):
                raise ValueError("Workspace does not exist")
            if await self._bindings.workspace_is_bound(workspace_id):
                raise ValueError("Workspace is already bound; implicit reassignment is forbidden")
        await self._bindings.insert(self._issuer, organization, workspace_id)
        return workspace_id

    async def disable(self, organization: str) -> None:
        organization = OrganizationId(organization).value
        if await self._bindings.find(self._issuer, organization) is None:
            raise ValueError("Organization has no local binding")
        await self._bindings.set_active(self._issuer, organization, False)
