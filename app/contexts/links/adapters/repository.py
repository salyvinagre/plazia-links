"""Reuse Zly's link persistence without importing its local user/authentication model."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.access.contracts import Principal
from app.contexts.links.application.management import (
    LinkConflictError,
    LinkDraft,
    LinkNotFoundError,
    LinkPage,
    LinkPatch,
    LinkView,
)
from app.models.link import Link
from app.schemas.link import LinkCreate, LinkUpdate
from app.services import link_service
from app.services.audit_service import log_audit_event


class SqlLinkRepository:
    def __init__(self, db: AsyncSession, workspace_id: str, actor: Principal) -> None:
        self._db = db
        self._workspace_id = workspace_id
        self._actor = actor

    @staticmethod
    def _view(link: Link) -> LinkView:
        return LinkView(
            link.id,
            link.short_code,
            link.destination_url,
            link.title,
            link.notes,
            link.is_active,
            link.created_at,
            link.updated_at,
        )

    async def _get(self, link_id: str) -> Link:
        link = await self._db.scalar(
            select(Link).where(Link.id == link_id, Link.workspace_id == self._workspace_id)
        )
        if link is None:
            raise LinkNotFoundError
        return link

    async def _audit(self, action: str, link_id: str) -> None:
        await log_audit_event(
            self._db,
            action=action,
            resource_type="link",
            resource_id=link_id,
            workspace_id=self._workspace_id,
            details=self._actor.actor_details(),
        )

    async def list(self, page: int, page_size: int) -> LinkPage:
        links, total, has_next = await link_service.get_links(
            self._db, self._workspace_id, page, page_size
        )
        return LinkPage([self._view(link) for link in links], total, page, page_size, has_next)

    async def get(self, link_id: str) -> LinkView:
        return self._view(await self._get(link_id))

    async def create(self, draft: LinkDraft) -> LinkView:
        for _ in range(5):
            try:
                # A code collision rolls back only this insert; the outer UoW stays usable.
                async with self._db.begin_nested():
                    link = await link_service.create_link(
                        self._db,
                        LinkCreate(
                            destination_url=draft.destination_url,
                            title=draft.title,
                            notes=draft.notes,
                            short_code=draft.short_code,
                            workspace_id=self._workspace_id,
                        ),
                        emit_webhooks=False,
                    )
                await self._audit("create", link.id)
                return self._view(link)
            except IntegrityError as exc:
                sqlstate = getattr(exc.orig, "sqlstate", None)
                if sqlstate != "23505" and "UNIQUE constraint failed: links.short_code" not in str(
                    exc.orig
                ):
                    raise
                if draft.short_code:
                    raise LinkConflictError from exc
        raise LinkConflictError

    async def update(self, link_id: str, patch: LinkPatch) -> LinkView:
        link = await self._get(link_id)
        values: dict[str, str | bool | None] = {
            field: getattr(patch, field) for field in patch.fields
        }
        updated = await link_service.update_link(self._db, link, LinkUpdate.model_validate(values))
        await self._audit("update", link_id)
        return self._view(updated)

    async def delete(self, link_id: str) -> None:
        link = await self._get(link_id)
        await link_service.delete_link(self._db, link, emit_webhooks=False)
        await self._audit("delete", link_id)
