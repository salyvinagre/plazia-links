"""Provider-neutral function profile and native Vercel deployment inputs."""

import importlib
import json
import tomllib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.pool import NullPool

from app.config import IdentitySettings, Settings
from app.contexts.links.contracts import ClickDraft
from app.platform.database import DatabaseRuntime
from app.platform.serverless import ServerlessPreflight

ROOT = Path(__file__).resolve().parents[2]


def configuration(**changes):
    return Settings(
        _env_file=None,
        **{
            "environment": "production",
            "deployment_mode": "serverless",
            "auth_mode": "identity",
            "secret_key": "test-only-secret-not-used-in-any-deployment-1234",
            "database_url": "postgresql+asyncpg://test:pass@database.example/preview?ssl=verify-full",
            "redis_url": "rediss://redis.example:6379/0",
            **changes,
        },
    )


def identity():
    return IdentitySettings(
        _env_file=None,
        issuer="https://issuer.example",
        audience="https://api.example",
        client_id="test-client",
        client_secret="test-only-client-secret",
        public_base_url="https://preview.example",
    )


def test_preflight_is_read_only_and_does_not_open_a_database_connection(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Build preflight must not connect or create an application")

    monkeypatch.setattr(DatabaseRuntime, "create_engine", unexpected)
    monkeypatch.setattr("socket.create_connection", unexpected)
    ServerlessPreflight.check(configuration(), identity())


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "test"},
        {"auth_mode": "legacy"},
        {"deployment_mode": "container"},
        {"database_url": "sqlite+aiosqlite:///:memory:"},
        {"database_url": "postgresql+asyncpg://db.example/preview"},
        {"database_url": "postgresql+asyncpg://db.example/preview?ssl=disable"},
        {"redis_url": "redis://redis.example/0"},
        {"secret_key": "REPLACE_WITH_REAL_SECRET"},
    ],
)
def test_insecure_or_incomplete_preview_configuration_is_rejected(changes):
    with pytest.raises((ValueError, RuntimeError)):
        ServerlessPreflight.check(configuration(**changes), identity())


@pytest.mark.asyncio
async def test_serverless_does_not_retain_database_connections_between_invocations():
    engine = DatabaseRuntime.create_engine(configuration())
    try:
        assert isinstance(engine.pool, NullPool)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_inline_click_binding_never_calls_the_queue(monkeypatch):
    from app.contexts.links.adapters.clicks import InlineClickRecorder
    from app.platform.links import click_recorder

    record = AsyncMock()
    queue = AsyncMock(side_effect=AssertionError("No queue in serverless mode"))
    monkeypatch.setattr("app.platform.links.settings", configuration())
    monkeypatch.setattr("app.contexts.links.adapters.clicks.record_click", record)
    monkeypatch.setattr("app.contexts.links.adapters.clicks.get_arq_pool", queue)
    db = AsyncMock()
    adapter = click_recorder(db)
    assert isinstance(adapter, InlineClickRecorder)
    await adapter.record(ClickDraft("link", "192.0.2.1", "test-agent", "https://example.com"))
    record.assert_awaited_once_with(
        db, "link", "192.0.2.1", "test-agent", "https://example.com", variant_id=None
    )
    queue.assert_not_awaited()


def test_native_and_legacy_entrypoints_export_the_same_application():
    actual = importlib.import_module("app.main").app
    assert importlib.import_module("app.index").app is actual
    assert importlib.import_module("api.index").app is actual


def test_manifest_preserves_url_paths_and_keeps_secrets_out_of_source():
    manifest = json.loads((ROOT / "vercel.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert manifest["framework"] == "fastapi"
    assert project["tool"]["vercel"]["entrypoint"] == "app.index:app"
    assert project["tool"]["vercel"]["scripts"]["build"] == "python -m app.platform.serverless"
    assert set(manifest["functions"]) == {"app/index.py"}
    assert not set(manifest) & {"env", "builds", "routes", "rewrites"}
    ignored = (ROOT / ".vercelignore").read_text().splitlines()
    assert ".env" in ignored and "tests/" in ignored
    assert not set(ignored) & {"app/", "migrations/", "alembic.ini", "uv.lock"}
