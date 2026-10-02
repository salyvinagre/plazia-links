"""Local authority: an explicit issuer/org binding, never an email-based match."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.access.domain.principal import AccessDeniedError, Principal
from app.models.identity import WorkspaceIdentityBinding
from app.models.workspace import Workspace


class WorkspaceAccess:
    @staticmethod
    async def resolve(db: AsyncSession, principal: Principal) -> Workspace:
        result = await db.execute(
            select(Workspace)
            .join(WorkspaceIdentityBinding, WorkspaceIdentityBinding.workspace_id == Workspace.id)
            .where(
                WorkspaceIdentityBinding.issuer == principal.issuer,
                WorkspaceIdentityBinding.organization_id == principal.organization_id,
                WorkspaceIdentityBinding.is_active.is_(True),
            )
        )
        workspace = result.scalar_one_or_none()
        if workspace is None:
            raise AccessDeniedError("unbound_organization")
        return workspace
