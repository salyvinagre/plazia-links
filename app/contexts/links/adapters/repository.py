"""SQL adapter for the canonical link table. No HTTP schemas or legacy service calls."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.links.application.models import LinkPage, LinkView
from app.contexts.links.domain.link import (
    LinkConflictError,
    LinkDraft,
    LinkNotFoundError,
    LinkPatch,
)
from app.models.link import Link


class SqlLinkRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

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

    async def _get(self, workspace_id: str, link_id: str) -> Link:
        link = await self._db.scalar(
            select(Link).where(Link.id == link_id, Link.workspace_id == workspace_id)
        )
        if link is None:
            raise LinkNotFoundError
        return link

    async def list(self, workspace_id: str, page: int, page_size: int) -> LinkPage:
        total = (
            await self._db.scalar(
                select(func.count()).select_from(Link).where(Link.workspace_id == workspace_id)
            )
            or 0
        )
        offset = (page - 1) * page_size
        links = (
            await self._db.scalars(
                select(Link)
                .where(Link.workspace_id == workspace_id)
                .order_by(Link.created_at.desc(), Link.id.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).all()
        return LinkPage(
            [self._view(link) for link in links], total, page, page_size, offset + page_size < total
        )

    async def get(self, workspace_id: str, link_id: str) -> LinkView:
        return self._view(await self._get(workspace_id, link_id))

    async def create(self, workspace_id: str, draft: LinkDraft) -> LinkView:
        try:
            # A collision rolls back only this insert; the request transaction stays usable.
            async with self._db.begin_nested():
                link = Link(
                    workspace_id=workspace_id,
                    short_code=draft.short_code,
                    destination_url=draft.destination_url,
                    title=draft.title,
                    notes=draft.notes,
                    user_id=None,
                )
                self._db.add(link)
                await self._db.flush()
                await self._db.refresh(link)
            return self._view(link)
        except IntegrityError as exc:
            cause = getattr(exc.orig, "__cause__", None)
            constraint = getattr(cause, "constraint_name", None)
            if (
                getattr(exc.orig, "sqlstate", None) == "23505"
                and constraint == "ix_links_short_code"
            ) or "UNIQUE constraint failed: links.short_code" in str(exc.orig):
                raise LinkConflictError from exc
            raise

    async def update(self, workspace_id: str, link_id: str, patch: LinkPatch) -> LinkView:
        link = await self._get(workspace_id, link_id)
        for field in patch.fields:
            setattr(link, field, getattr(patch, field))
        link.updated_at = datetime.now(UTC)
        await self._db.flush()
        await self._db.refresh(link)
        return self._view(link)

    async def delete(self, workspace_id: str, link_id: str) -> None:
        await self._db.delete(await self._get(workspace_id, link_id))
        await self._db.flush()
