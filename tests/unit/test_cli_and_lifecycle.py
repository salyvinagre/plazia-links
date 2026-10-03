from unittest.mock import AsyncMock, Mock

import pytest
from shared_identity import OrganizationId

from app.interfaces import cli
from app.interfaces.cli import OperatorCli
from app.platform import composition
from tests.support import MemoryUowFactory


def test_cli_help_does_not_read_runtime_secrets(tmp_path):
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env.pop("PLZK_SCHEMA_DATABASE_URL", None)
    env["PLZK_SCHEMA_DATABASE_URL_FILE"] = str(tmp_path / "missing-secret")
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "bind-organization" in result.stdout and "schema-check" in result.stdout


async def test_operator_binds_disables_and_closes_owner_scope(
    monkeypatch, issuer, database, identity_db
):
    monkeypatch.setattr(cli, "PublicSettings", issuer.config)
    monkeypatch.setattr(composition, "PostgresDatabase", lambda *args, **kwargs: database)
    database.close = AsyncMock()
    monkeypatch.setattr(composition, "PostgresUowFactory", MemoryUowFactory)
    org = OrganizationId.new()
    assert (
        await OperatorCli.router().run_async(["bind-organization", str(org), "--name", "Launch"])
        == 0
    )
    assert identity_db.bindings[org].name == "Launch" and identity_db.bindings[org].is_active
    assert await OperatorCli.router().run_async(["disable-organization", str(org)]) == 0
    assert not identity_db.bindings[org].is_active and database.close.await_count == 2
    monkeypatch.setattr(cli, "PublicSettings", lambda: type("Identity", (), {"issuer": ""})())
    assert (
        await OperatorCli.router().run_async(["bind-organization", str(org), "--name", "Launch"])
        == 1
    )


@pytest.mark.parametrize("action", ["prepare", "finish", "check"])
async def test_operator_schema_commands_only_invoke_readonly_authority(monkeypatch, action, capsys):
    authority = Mock()
    monkeypatch.setattr(cli, "SchemaAuthority", lambda *args: authority)
    assert await OperatorCli.router().run_async(["schema-" + action]) == 0
    getattr(authority, action).assert_called_once_with()
    assert "verified" in capsys.readouterr().out


async def test_operator_usage_and_target_failures_are_redacted(monkeypatch, capsys):
    def failed(*args):
        raise OSError("postgresql://private-user:private-password@private-host/db")

    monkeypatch.setattr(cli, "SchemaAuthority", failed)
    assert await OperatorCli.router().run_async(["schema-check"]) == 1
    error = capsys.readouterr().err
    assert "Operator action failed" in error and "private" not in error
    assert await OperatorCli.router().run_async(["bind-organization"]) == 2


async def test_redis_runtime_uses_shared_secret_pool_and_closes_once(monkeypatch):
    from app.platform import redis

    pool = Mock(disconnect=AsyncMock())
    monkeypatch.setattr(redis, "pool", None)
    factory = Mock(return_value=pool)
    monkeypatch.setattr(redis.ConnectionPool, "from_url", factory)
    monkeypatch.setattr(redis, "Redis", lambda **kwargs: kwargs["connection_pool"])
    assert await redis.get_redis() is pool and await redis.get_redis() is pool
    assert factory.call_count == 1
    await redis.close_redis()
    await redis.close_redis()
    pool.disconnect.assert_awaited_once()
