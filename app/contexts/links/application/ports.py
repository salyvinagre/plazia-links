"""Persistence and audit ports owned by the link-management use cases."""

from typing import Literal, Protocol

from app.contexts.access.contracts import Principal
from app.contexts.links.application.models import ClickDraft, LinkPage, LinkView
from app.contexts.links.domain.link import LinkDraft, LinkPatch

AuditAction = Literal["create", "update", "delete"]


class LinkRepository(Protocol):
    async def list(self, workspace_id: str, page: int, page_size: int) -> LinkPage: ...
    async def get(self, workspace_id: str, link_id: str) -> LinkView: ...
    async def create(self, workspace_id: str, draft: LinkDraft) -> LinkView: ...
    async def update(self, workspace_id: str, link_id: str, patch: LinkPatch) -> LinkView: ...
    async def delete(self, workspace_id: str, link_id: str) -> None: ...


class LinkAudit(Protocol):
    async def record(
        self, action: AuditAction, workspace_id: str, link_id: str, principal: Principal
    ) -> None: ...


class ClickRecorder(Protocol):
    async def record(self, click: ClickDraft) -> None: ...
