"""Adapters for the inherited click recorder and queue; no deploy-mode branching."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.links.application.models import ClickDraft
from app.contexts.links.application.ports import ClickRecorder
from app.core.arq_pool import get_arq_pool
from app.core.logging import get_logger
from app.services.click_service import record_click

logger = get_logger(__name__)


class InlineClickRecorder:
    """Bridge to existing analytics persistence; work finishes inside the request."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record(self, click: ClickDraft) -> None:
        await record_click(
            self._db,
            click.link_id,
            click.ip,
            click.user_agent,
            click.referrer,
            variant_id=click.variant_id,
        )


class QueuedClickRecorder:
    def __init__(self, fallback: ClickRecorder) -> None:
        self._fallback = fallback

    async def record(self, click: ClickDraft) -> None:
        try:
            pool = await get_arq_pool()
            await pool.enqueue_job(
                "process_click",
                link_id=click.link_id,
                ip=click.ip,
                user_agent=click.user_agent,
                referrer=click.referrer,
                variant_id=click.variant_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to enqueue click; recording synchronously", extra={"error": str(exc)}
            )
            await self._fallback.record(click)
