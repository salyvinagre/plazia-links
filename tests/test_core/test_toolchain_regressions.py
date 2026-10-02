"""Regressions uncovered while enabling strict checks on Python 3.14."""

from unittest.mock import AsyncMock

import pytest
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.click import Click
from app.services.analytics_service import get_hourly_stats


def test_worker_configuration_uses_supported_arq_api() -> None:
    from worker.run import WorkerSettings

    assert isinstance(WorkerSettings.redis_settings, RedisSettings)
    assert {job.coroutine.__name__ for job in WorkerSettings.cron_jobs} == {
        "cleanup_old_data",
        "sweep_expiring_links",
    }


@pytest.mark.asyncio
async def test_arq_pool_can_be_created(monkeypatch) -> None:
    from app.core import arq_pool

    pool = AsyncMock()
    create_pool = AsyncMock(return_value=pool)
    monkeypatch.setattr(arq_pool, "_pool", None)
    monkeypatch.setattr(arq_pool, "create_pool", create_pool)
    assert await arq_pool.get_arq_pool() is pool
    assert isinstance(create_pool.call_args.args[0], RedisSettings)
    await arq_pool.close_arq_pool()


@pytest.mark.asyncio
async def test_hourly_analytics_also_supports_sqlite(
    db_session: AsyncSession, test_workspace_id: str
) -> None:
    from datetime import UTC, datetime

    from app.models.link import Link

    link = Link(
        short_code="hourcheck",
        workspace_id=test_workspace_id,
        destination_url="https://example.com",
    )
    db_session.add(link)
    await db_session.flush()
    db_session.add(Click(link_id=link.id, timestamp=datetime(2026, 10, 2, 9, tzinfo=UTC)))
    await db_session.flush()
    assert await get_hourly_stats(db_session, link.id) == [{"hour": "09", "count": 1}]
