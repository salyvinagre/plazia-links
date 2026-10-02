"""Operator-only local tenant binding. No request-time or email-based provisioning."""

from uuid import UUID, uuid7

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import WorkspaceIdentityBinding
from app.models.workspace import Workspace


class WorkspaceProvisioning:
    def __init__(self, db: AsyncSession, issuer: str) -> None:
        self._db = db
        self._issuer = issuer

    @staticmethod
    def organization(value: str) -> str:
        if not value.startswith("org_"):
            raise ValueError("Organization must be a canonical org_<uuidv7>")
        identifier = UUID(value[4:])
        if identifier.version != 7 or value != f"org_{identifier}":
            raise ValueError("Organization must be a canonical org_<uuidv7>")
        return value

    async def bind(self, organization: str, name: str, workspace_id: str | None = None) -> str:
        organization = self.organization(organization)
        if not 1 <= len(name.strip()) <= 100:
            raise ValueError("Workspace name must contain 1–100 characters")
        existing = await self._db.scalar(
            select(WorkspaceIdentityBinding).where(
                WorkspaceIdentityBinding.issuer == self._issuer,
                WorkspaceIdentityBinding.organization_id == organization,
            )
        )
        if existing:
            if workspace_id is not None and existing.workspace_id != workspace_id:
                raise ValueError("Organization is already bound to a different workspace")
            existing.is_active = True
            await self._db.flush()
            return existing.workspace_id
        workspace: Workspace | None
        if workspace_id is None:
            identifier = str(uuid7())
            workspace = Workspace(id=identifier, name=name.strip(), slug=identifier, owner_id=None)
            self._db.add(workspace)
            await self._db.flush()
        else:
            workspace = await self._db.get(Workspace, workspace_id)
            if workspace is None:
                raise ValueError("Workspace does not exist")
            if await self._db.get(WorkspaceIdentityBinding, workspace.id) is not None:
                raise ValueError("Workspace is already bound; implicit reassignment is forbidden")
        self._db.add(
            WorkspaceIdentityBinding(
                workspace_id=workspace.id,
                issuer=self._issuer,
                organization_id=organization,
            )
        )
        await self._db.flush()
        return workspace.id

    async def disable(self, organization: str) -> None:
        organization = self.organization(organization)
        binding = await self._db.scalar(
            select(WorkspaceIdentityBinding).where(
                WorkspaceIdentityBinding.issuer == self._issuer,
                WorkspaceIdentityBinding.organization_id == organization,
            )
        )
        if binding is None:
            raise ValueError("Organization has no local binding")
        binding.is_active = False
        await self._db.flush()
