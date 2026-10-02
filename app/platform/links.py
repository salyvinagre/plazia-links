"""Deployment-specific binding of link side effects; the adapters own execution."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.contexts.links.adapters.clicks import InlineClickRecorder, QueuedClickRecorder
from app.contexts.links.application.ports import ClickRecorder


def click_recorder(db: AsyncSession) -> ClickRecorder:
    inline = InlineClickRecorder(db)
    return inline if settings.deployment_mode == "serverless" else QueuedClickRecorder(inline)
