"""Authorized link use cases shared by JSON, browser and future command adapters."""

from dataclasses import replace

from app.contexts.access.contracts import Permission, Principal, WorkspaceResolver
from app.contexts.links.application.models import LinkPage, LinkView
from app.contexts.links.application.ports import LinkAudit, LinkRepository
from app.contexts.links.domain.link import (
    InvalidLinkError,
    LinkConflictError,
    LinkDraft,
    LinkPatch,
    PublicCode,
)


class LinkManagement:
    def __init__(
        self,
        principal: Principal,
        workspaces: WorkspaceResolver,
        repository: LinkRepository,
        audit: LinkAudit,
    ) -> None:
        self.principal = principal
        self._workspaces = workspaces
        self._repository = repository
        self._audit = audit

    async def _workspace(self, permission: Permission) -> str:
        self.principal.require(permission)
        return (await self._workspaces.resolve(self.principal)).id

    async def list(self, page: int = 1, page_size: int = 20) -> LinkPage:
        workspace = await self._workspace("read:links")
        if page < 1 or not 1 <= page_size <= 100:
            raise InvalidLinkError("Invalid pagination")
        return await self._repository.list(workspace, page, page_size)

    async def get(self, link_id: str) -> LinkView:
        return await self._repository.get(await self._workspace("read:links"), link_id)

    async def create(self, draft: LinkDraft) -> LinkView:
        workspace = await self._workspace("create:links")
        # Allocation/retry policy belongs here, not in the SQL driver.
        for _ in range(5):
            candidate = (
                draft if draft.short_code else replace(draft, short_code=PublicCode.generate())
            )
            try:
                link = await self._repository.create(workspace, candidate)
            except LinkConflictError:
                if draft.short_code:
                    raise
                continue
            await self._audit.record("create", workspace, link.id, self.principal)
            return link
        raise LinkConflictError

    async def update(self, link_id: str, patch: LinkPatch) -> LinkView:
        workspace = await self._workspace("update:links")
        link = await self._repository.update(workspace, link_id, patch)
        await self._audit.record("update", workspace, link_id, self.principal)
        return link

    async def delete(self, link_id: str) -> None:
        workspace = await self._workspace("delete:links")
        await self._repository.delete(workspace, link_id)
        await self._audit.record("delete", workspace, link_id, self.principal)
