"""SQL bridge for the existing workspace tables. It makes no access-policy decisions."""

from uuid import uuid7

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.access.adapters.models import WorkspaceIdentityBinding
from app.contexts.access.application.models import WorkspaceBinding, WorkspaceView
from app.models.workspace import Workspace


class SqlWorkspaceBindings:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def find(self, issuer: str, organization: str) -> WorkspaceBinding | None:
        row = (
            await self._db.execute(
                select(Workspace, WorkspaceIdentityBinding)
                .join(
                    WorkspaceIdentityBinding, WorkspaceIdentityBinding.workspace_id == Workspace.id
                )
                .where(
                    WorkspaceIdentityBinding.issuer == issuer,
                    WorkspaceIdentityBinding.organization_id == organization,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        workspace, binding = row
        return WorkspaceBinding(WorkspaceView(workspace.id, workspace.name), binding.is_active)

    async def workspace_exists(self, workspace_id: str) -> bool:
        return await self._db.get(Workspace, workspace_id) is not None

    async def workspace_is_bound(self, workspace_id: str) -> bool:
        return await self._db.get(WorkspaceIdentityBinding, workspace_id) is not None

    async def create_workspace(self, name: str) -> str:
        identifier = str(uuid7())
        self._db.add(Workspace(id=identifier, name=name, slug=identifier, owner_id=None))
        await self._db.flush()
        return identifier

    async def insert(self, issuer: str, organization: str, workspace_id: str) -> None:
        self._db.add(
            WorkspaceIdentityBinding(
                issuer=issuer, organization_id=organization, workspace_id=workspace_id
            )
        )
        await self._db.flush()

    async def set_active(self, issuer: str, organization: str, active: bool) -> None:
        await self._db.execute(
            update(WorkspaceIdentityBinding)
            .where(
                WorkspaceIdentityBinding.issuer == issuer,
                WorkspaceIdentityBinding.organization_id == organization,
            )
            .values(is_active=active)
        )
        await self._db.flush()
