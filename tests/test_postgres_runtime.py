"""Run only against an explicitly supplied, already migrated test database."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.click import Click
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.link import LinkCreate, LinkUpdate
from app.services.analytics_service import get_hourly_stats
from app.services.link_service import create_link, get_link_by_id, update_link

POSTGRES_TEST_URL = os.environ.get("POSTGRES_TEST_URL", "")
pytestmark = pytest.mark.skipif(not POSTGRES_TEST_URL, reason="POSTGRES_TEST_URL not configured")


@pytest_asyncio.fixture
async def postgres_session() -> AsyncIterator[AsyncSession]:
    assert POSTGRES_TEST_URL.startswith("postgresql+asyncpg://")
    engine = create_async_engine(POSTGRES_TEST_URL, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(connection, expire_on_commit=False)
            async with factory() as session:
                yield session
            await transaction.rollback()
    finally:
        await engine.dispose()


async def seed_workspace(session: AsyncSession) -> Workspace:
    user = User(email=f"postgres-{uuid4().hex}@example.com", is_active=True)
    session.add(user)
    await session.flush()
    workspace = Workspace(name="PostgreSQL regression", slug=uuid4().hex, owner_id=user.id)
    session.add(workspace)
    await session.flush()
    return workspace


@pytest.mark.asyncio
async def test_postgres18_uses_versioned_schema(postgres_session: AsyncSession) -> None:
    version = await postgres_session.scalar(text("SHOW server_version_num"))
    assert 180000 <= int(version) < 190000
    revisions = (
        await postgres_session.execute(text("SELECT version_num FROM alembic_version"))
    ).all()
    assert len(revisions) == 1
    # This must exist through Alembic, never via metadata.create_all in this fixture.
    assert await postgres_session.scalar(text("SELECT to_regclass('public.folders')")) == "folders"


@pytest.mark.asyncio
async def test_postgres_link_create_update(postgres_session: AsyncSession, monkeypatch) -> None:
    from unittest.mock import AsyncMock

    # Cache delivery is a separate integration; keep this test about SQL/runtime behavior.
    monkeypatch.setattr("app.services.link_service._invalidate_link_cache", AsyncMock())
    workspace = await seed_workspace(postgres_session)
    link = await create_link(
        postgres_session,
        LinkCreate(
            workspace_id=workspace.id,
            destination_url="https://example.com/first",
            notes="created on PostgreSQL 18",
            max_clicks=12,
        ),
        user_id=workspace.owner_id,
    )
    assert link.notes == "created on PostgreSQL 18"
    assert link.max_clicks == 12
    await update_link(
        postgres_session, link, LinkUpdate(destination_url="https://example.com/second")
    )
    loaded = await get_link_by_id(postgres_session, link.id)
    assert loaded is not None
    assert loaded.destination_url == "https://example.com/second"
    assert loaded.workspace_id == workspace.id


@pytest.mark.asyncio
async def test_postgres_hourly_analytics(postgres_session: AsyncSession) -> None:
    workspace = await seed_workspace(postgres_session)
    link = await create_link(
        postgres_session,
        LinkCreate(workspace_id=workspace.id, destination_url="https://example.com/analytics"),
        user_id=workspace.owner_id,
    )
    postgres_session.add_all(
        [
            Click(link_id=link.id, timestamp=datetime(2026, 10, 2, 8, minute, tzinfo=UTC))
            for minute in (0, 15)
        ]
        + [Click(link_id=link.id, timestamp=datetime(2026, 10, 2, 19, 0, tzinfo=UTC))]
    )
    await postgres_session.flush()
    assert await get_hourly_stats(postgres_session, link.id) == [
        {"hour": "08", "count": 2},
        {"hour": "19", "count": 1},
    ]
    assert (
        len((await postgres_session.scalars(select(Click).where(Click.link_id == link.id))).all())
        == 3
    )
