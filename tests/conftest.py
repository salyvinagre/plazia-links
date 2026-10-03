import httpx
import pytest

from app.main import create_app
from app.platform.access import AccessRuntime
from app.platform.settings import Settings
from tests.identity_support import LinksIssuer, MemoryState
from tests.support import FixtureAuthority, MemoryDatabase, MemoryRepository, MemoryUowFactory


@pytest.fixture
def issuer():
    value = LinksIssuer()
    yield value
    value.close()


@pytest.fixture
def ephemeral():
    return MemoryState()


@pytest.fixture
def identity_db(issuer):
    return MemoryRepository(issuer.url)


@pytest.fixture
def authority():
    return FixtureAuthority()


@pytest.fixture
def database(identity_db):
    return MemoryDatabase(identity_db)


@pytest.fixture
def application(issuer, ephemeral, database, authority):
    return create_app(
        access=AccessRuntime.build(issuer.config(), ephemeral),
        database=database,
        uow_factory=MemoryUowFactory(database),
        authority=authority,
        config=Settings(rate_limit_enabled=False),
    )


@pytest.fixture
async def identity_client(application):
    async def creation_key(request):
        from uuid import uuid4

        if request.method in {"POST", "PATCH", "DELETE"} and request.url.path.startswith(
            "/api/v1/"
        ):
            request.headers.setdefault("Idempotency-Key", uuid4().hex)
        elif request.method == "POST" and request.url.path.startswith("/dashboard/"):
            # Most fast tests construct browser posts; real browser proof uses the hidden form key.
            request.headers.setdefault("Idempotency-Key", uuid4().hex)

    async with httpx.AsyncClient(
        event_hooks={"request": [creation_key]},
        transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
        base_url="http://127.0.0.1:8000",
        follow_redirects=False,
    ) as client:
        yield client


def pytest_bdd_apply_tag(tag, function):
    if tag.startswith("story:"):
        return True
    return None
