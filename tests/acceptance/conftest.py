from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.access.adapters.models import WorkspaceIdentityBinding
from app.core.dependencies import get_db
from app.db import Base
from app.main import create_app
from app.models.workspace import Workspace
from app.platform.access import AccessRuntime
from tests.identity_support import ORG_A, ORG_B, LocalIssuer, MemoryState


@pytest.fixture
def issuer():
    value = LocalIssuer()
    yield value
    value.close()


@pytest.fixture
def ephemeral():
    return MemoryState()


@pytest_asyncio.fixture
async def identity_db(tmp_path) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/identity.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


@pytest_asyncio.fixture
async def identity_client(identity_db, issuer, ephemeral, monkeypatch):
    auth = AccessRuntime.build(issuer.config(), ephemeral)
    app = create_app(auth_mode="identity", access=auth)
    for organization, slug in [(ORG_A, "tenant-a"), (ORG_B, "tenant-b")]:
        workspace = Workspace(name=slug, slug=slug)
        identity_db.add(workspace)
        await identity_db.flush()
        identity_db.add(
            WorkspaceIdentityBinding(
                workspace_id=workspace.id, issuer=issuer.url, organization_id=organization
            )
        )
    await identity_db.commit()

    async def database():
        try:
            yield identity_db
            await identity_db.commit()
        except Exception:
            await identity_db.rollback()
            raise

    async def unavailable_queue():
        raise ConnectionError("Use the synchronous click recorder in this boundary test")

    async def invalidate(*args):
        pass

    # These tests exercise auth, authorization and SQL, not Redis analytics or ARQ delivery.
    monkeypatch.setattr("app.contexts.links.adapters.clicks.get_arq_pool", unavailable_queue)
    monkeypatch.setattr("app.services.link_service._invalidate_link_cache", invalidate)
    app.dependency_overrides[get_db] = database
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=auth.config.public_base_url
    ) as client:
        yield client
