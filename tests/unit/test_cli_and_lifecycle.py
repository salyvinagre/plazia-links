from argparse import Namespace
from unittest.mock import AsyncMock, Mock

import pytest
from shared_identity import OrganizationId

from app import cli
from tests.support import MemoryUowFactory


async def test_operator_binds_disables_and_closes_owner_scope(
    monkeypatch, issuer, database, identity_db
):
    monkeypatch.setattr(cli, "IdentitySettings", issuer.config)
    monkeypatch.setattr(cli, "PostgresDatabase", lambda *args, **kwargs: database)
    database.close = AsyncMock()
    monkeypatch.setattr(cli, "PostgresUowFactory", MemoryUowFactory)
    org = OrganizationId.new()
    await cli.provision(Namespace(action="bind-organization", organization=str(org), name="Launch"))
    assert identity_db.bindings[org].name == "Launch" and identity_db.bindings[org].is_active
    await cli.provision(Namespace(action="disable-organization", organization=str(org)))
    assert not identity_db.bindings[org].is_active and database.close.await_count == 2
    monkeypatch.setattr(cli, "IdentitySettings", lambda: type("Identity", (), {"issuer": ""})())
    with pytest.raises(ValueError, match="ISSUER"):
        await cli.provision(
            Namespace(action="bind-organization", organization=str(org), name="Launch")
        )


@pytest.mark.parametrize("action", ["prepare", "finish", "check"])
def test_operator_schema_commands_only_invoke_readonly_authority(monkeypatch, action, capsys):
    authority = Mock()
    monkeypatch.setattr(cli, "SchemaAuthority", lambda *args: authority)
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda *args: Namespace(action="schema-" + action),
    )
    cli.main()
    getattr(authority, action).assert_called_once_with()
    assert "verified" in capsys.readouterr().out


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
