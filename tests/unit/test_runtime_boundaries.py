"""Runtime failures, secret selection and authority boundaries without services."""

import json
import logging
import time
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import RedisError
from shared_identity import OrganizationId

from app.contexts.access.adapters.authorization import OpenFgaOrganizationAuthority
from app.contexts.access.adapters.redis_state import RedisState
from app.contexts.access.application.authorization import AuthorizationAttempt
from app.contexts.access.contracts import AccessDeniedError, AccessUnavailableError, Principal
from app.platform.settings import IdentitySettings, Settings
from tests.identity_support import ORG_A


@pytest.fixture
def principal():
    return Principal(
        "https://identity.example",
        "usr_0199a112345670008000000000000003",
        "client",
        OrganizationId(ORG_A),
        frozenset({"links:read", "links:create"}),
        int(time.time()) + 300,
        "token",
    )


async def test_openfga_reader_manager_machine_and_denial(principal):
    authority = OpenFgaOrganizationAuthority("http://localhost:8080", "store", "model")
    client = authority._client
    authority._client = AsyncMock()
    authority._client.check.return_value.allowed = True
    await authority.require(AuthorizationAttempt(principal, "links:read", None))
    assert authority._client.check.await_args.args[0].relation == "reader"
    await authority.require(
        AuthorizationAttempt(
            replace(principal, subject="mch_0199a112345670008000000000000004"), "links:create", None
        )
    )
    request = authority._client.check.await_args.args[0]
    assert request.relation == "manager" and request.user.startswith("machine:mch_")
    assert request.object == "organization:" + ORG_A
    authority._client.check.return_value.allowed = False
    with pytest.raises(AccessDeniedError):
        await authority.require(AuthorizationAttempt(principal, "links:read", None))
    authority._client.check.side_effect = OSError("private endpoint")
    with pytest.raises(AccessUnavailableError):
        await authority.require(AuthorizationAttempt(principal, "links:read", None))
    await authority.close()
    await client.close()


def test_missing_authority_configuration_is_rejected():
    with pytest.raises(ValueError):
        OpenFgaOrganizationAuthority("", "", "")


@pytest.mark.parametrize(
    "method,args",
    [
        ("put", ("session", "key", "value", 300)),
        ("get", ("session", "key")),
        ("take", ("session", "key")),
        ("remove", ("session", "key")),
        ("consume_once", ("proof", 60)),
    ],
)
async def test_redis_outages_fail_closed(method, args):
    redis = AsyncMock()
    redis.set.side_effect = RedisError()
    redis.get.side_effect = RedisError()
    redis.getdel.side_effect = RedisError()
    redis.delete.side_effect = RedisError()
    getter = AsyncMock(return_value=redis)
    with pytest.raises(AccessUnavailableError):
        await getattr(RedisState(getter), method)(*args)


async def test_redis_keys_are_hashed_and_state_is_consumed_atomically():
    redis = AsyncMock()
    redis.get.return_value = "state"
    redis.getdel.return_value = None
    redis.set.return_value = True
    store = RedisState(AsyncMock(return_value=redis))
    await store.put("session", "private-handle", "value", 0)
    key = redis.set.await_args.args[0]
    assert "private-handle" not in key and redis.set.await_args.kwargs["ex"] == 1
    assert await store.get("session", "private-handle") == "state"
    assert await store.take("session", "private-handle") is None
    await store.remove("session", "private-handle")
    assert await store.consume_once("proof", 60)
    assert redis.set.await_args.kwargs == {"nx": True, "ex": 60}


def test_plzl_secret_file_toml_precedence_and_guard(monkeypatch, tmp_path):
    from shared_settings.secrets import SettingsError

    config = tmp_path / "runtime.toml"
    config.write_text("[app]\nworker_interval=9\n[identity]\nsession_ttl=600\n")
    config.chmod(0o600)
    monkeypatch.setenv("PLZL_CONFIG_FILE", str(config))
    assert Settings().worker_interval == 9 and IdentitySettings().session_ttl == 600
    monkeypatch.setenv("PLZL_WORKER_INTERVAL", "7")
    assert Settings().worker_interval == 7 and Settings(worker_interval=3).worker_interval == 3
    secret = tmp_path / "database-url"
    secret.write_text("postgresql://links_app@db/links")
    secret.chmod(0o600)
    monkeypatch.setenv("PLZL_DATABASE_URL_FILE", str(secret))
    assert Settings().database_url.get_secret_value() == "postgresql://links_app@db/links"
    monkeypatch.setenv("PLZL_DATABASE_URL", "postgresql://other")
    with pytest.raises(SettingsError):
        Settings()
    monkeypatch.delenv("PLZL_DATABASE_URL")
    monkeypatch.delenv("PLZL_DATABASE_URL_FILE")
    config.write_text('[app]\ndatabase_url="postgresql://secret"\n')
    with pytest.raises(SettingsError):
        Settings()


@pytest.mark.parametrize(
    ("trusted", "headers", "expected"),
    [
        (False, [("X-Forwarded-For", "203.0.113.1")], "10.0.0.10"),
        (True, [("X-Forwarded-For", "203.0.113.1")], "203.0.113.1"),
        (True, [("X-Forwarded-For", "spoofed, 203.0.113.2")], "203.0.113.2"),
        (True, [("X-Forwarded-For", "spoofed")], "10.0.0.10"),
        (
            True,
            [("X-Forwarded-For", "203.0.113.1"), ("X-Forwarded-For", "203.0.113.2")],
            "10.0.0.10",
        ),
    ],
)
async def test_rate_identity_requires_exact_trusted_peer(
    application, monkeypatch, trusted, headers, expected
):
    import hashlib

    import httpx

    from app.interfaces.middleware import rate_limiter

    redis = AsyncMock()
    redis.eval.return_value = [1, 60]
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=redis))
    rate_limiter.setup_rate_limiter(
        application, frozenset({"10.0.0.10"}) if trusted else frozenset()
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, client=("10.0.0.10", 123)),
        base_url="http://links.test",
    ) as client:
        assert (await client.get("/unknown", headers=headers)).status_code == 404
    assert redis.eval.await_args.args[2].endswith(hashlib.sha256(expected.encode()).hexdigest())


async def test_rate_admission_atomic_and_unavailable(application, monkeypatch):
    import httpx

    from app.interfaces.middleware import rate_limiter

    redis = AsyncMock()
    redis.eval.return_value = [21, 30]
    monkeypatch.setattr(rate_limiter, "get_redis", AsyncMock(return_value=redis))
    rate_limiter.setup_rate_limiter(application)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://127.0.0.1:8000"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        denied = await client.post("/unknown/subscriptions", headers={"X-Forwarded-For": "spoofed"})
        assert denied.status_code == 429 and denied.headers["retry-after"] == "30"
        assert "spoofed" not in redis.eval.await_args.args[2]
        redis.eval.side_effect = RedisError()
        assert (await client.get("/login")).status_code == 503
        redis.eval.side_effect = None
        redis.eval.return_value = [1, 60]
        assert (await client.get("/")).status_code == 303


def test_logging_preserves_safe_request_id():
    from app.interfaces.middleware.request_id import request_id_var
    from app.platform.logging import JSONFormatter, LoggerAdapter, setup_logging

    setup_logging()
    request_id_var.set("operation-1")
    logger = LoggerAdapter(logging.getLogger("fixture"), {})
    msg, kwargs = logger.process("safe message", {})
    record = logging.makeLogRecord(
        {"msg": msg, "levelname": "INFO", "name": "fixture", **kwargs["extra"]}
    )
    payload = json.loads(JSONFormatter().format(record))
    assert payload["request_id"] == "operation-1" and payload["msg"] == "safe message"


async def test_startup_composes_readonly_schema_and_closes_runtime(monkeypatch, issuer):
    from app import main
    from app.platform.access import AccessRuntime
    from tests.identity_support import MemoryState
    from tests.support import FixtureAuthority, MemoryDatabase, MemoryRepository, MemoryUowFactory

    db = MemoryDatabase(MemoryRepository(issuer.url))
    db.close = AsyncMock()
    authority = FixtureAuthority()
    authority.close = AsyncMock()
    schema = AsyncMock()
    from unittest.mock import Mock

    schema = Mock()
    monkeypatch.setattr(main, "SchemaAuthority", lambda *args: schema)
    monkeypatch.setattr(main, "PostgresDatabase", lambda *args, **kwargs: db)
    monkeypatch.setattr(main, "PostgresUowFactory", MemoryUowFactory)
    monkeypatch.setattr(main, "OpenFgaOrganizationAuthority", lambda *args: authority)
    monkeypatch.setattr(main, "IdentitySettings", issuer.config)
    monkeypatch.setattr(main, "get_redis", AsyncMock(return_value=AsyncMock()))
    monkeypatch.setattr(main, "close_redis", AsyncMock())
    builder = Mock(return_value=AccessRuntime.build(issuer.config(), MemoryState()))
    monkeypatch.setattr(main.AccessRuntime, "build", builder)
    application = main.create_app(config=Settings(rate_limit_enabled=False))
    async with application.router.lifespan_context(application):
        schema.check.assert_called_once()
        assert application.state.commands.handles(
            __import__(
                "app.contexts.links.contracts", fromlist=["ReservePoolCommand"]
            ).ReservePoolCommand
        )
    db.close.assert_awaited_once()
    authority.close.assert_awaited_once()


def test_domain_validation_rejects_private_ambiguous_and_reserved_inputs():
    from shared_kernel import CanonicalIds

    from app.contexts.links.domain.link import Destination, LinkDraft, LinkPatch, PublicCode
    from app.kernel.ids import LinkId, PoolId

    for url in (
        "https://localhost",
        "http://192.168.1.1",
        "http://2130706433",
        "https://user:pass@example.com",
        "https://example.com:bad",
        "https://example.com/ a",
        "http://[::1]",
    ):
        with pytest.raises(ValueError):
            Destination(url)
    for code in ("login", "too-long-code", "a b"):
        with pytest.raises(ValueError):
            PublicCode(code)
    with pytest.raises(ValueError):
        LinkDraft(None)
    with pytest.raises(ValueError):
        LinkPatch(frozenset())
    with pytest.raises(ValueError):
        LinkPatch(frozenset({"destination_url"}))
    with pytest.raises(ValueError):
        LinkPatch(frozenset({"is_active"}), is_active="yes")
    assert isinstance(CanonicalIds.parse(str(LinkId.new())), LinkId)
    assert isinstance(CanonicalIds.parse(str(PoolId.new())), PoolId)
