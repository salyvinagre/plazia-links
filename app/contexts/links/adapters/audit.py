"""Audit persistence participates in the same transaction as the link write."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.access.contracts import Principal
from app.contexts.links.application.ports import AuditAction
from app.models.audit import AuditLog


class SqlLinkAudit:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record(
        self, action: AuditAction, workspace_id: str, link_id: str, principal: Principal
    ) -> None:
        self._db.add(
            AuditLog(
                workspace_id=workspace_id,
                action=action,
                resource_type="link",
                resource_id=link_id,
                details=json.dumps(principal.actor_details()),
            )
        )
        await self._db.flush()
