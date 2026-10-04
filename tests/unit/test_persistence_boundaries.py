"""Persistence adapters keep shared identities and transaction boundaries intact."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import fields
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid7

import pytest
from psycopg.errors import UniqueViolation
from shared_identity.canonical_ids import OrganizationId

from app.contexts.access.adapters.repositories.sql.postgres import PostgresOrganizationRepository
from app.contexts.links.adapters.repositories.sql.postgres import PostgresLinkRepository
from app.contexts.links.application.dto.links import PublicLinkDto
from app.contexts.links.domain.link import LinkConflictError, LinkDraft
from app.kernel.ids import LinkId, PoolId
from app.platform import database as database_module
from app.platform.database import PostgresDatabase, PostgresUowFactory
from app.platform.persistence import schema as schema_module
from app.platform.persistence.schema import SchemaAuthority, SchemaError

_NOW = datetime.now(UTC)


class _Cursor:
    def __init__(
        self, *, row: tuple[Any, ...] | None = None, rows: list[tuple[Any, ...]] | None = None
    ):
        self._row = row
        self._rows = rows or []

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _Savepoint:
    def __init__(self) -> None:
        self.exit_error: type[BaseException] | None = None

    async def __aenter__(self) -> _Savepoint:
        return self

    async def __aexit__(self, error_type: type[BaseException] | None, *_: object) -> bool:
        self.exit_error = error_type
        return False


class _AsyncConnection:
    def __init__(self, execute: Callable[[str, tuple[object, ...]], _Cursor]) -> None:
        self.execute_script = execute
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.savepoints: list[_Savepoint] = []

    async def execute(self, query: str, params: tuple[object, ...] = ()) -> _Cursor:
        self.calls.append((query, params))
        return self.execute_script(query, params)

    def transaction(self) -> _Savepoint:
        savepoint = _Savepoint()
        self.savepoints.append(savepoint)
        return savepoint


def _link_row(
    organization_id: OrganizationId,
    link_id: UUID,
    pool_id: UUID | None,
    short_code: str = "abc123",
) -> tuple[Any, ...]:
    return (
        link_id,
        organization_id.uuid,
        pool_id,
        short_code,
        None,
        None,
        None,
        True,
        _NOW,
        _NOW,
    )


@pytest.mark.asyncio
async def test_repository_maps_database_uuids_to_canonical_ids_and_scopes_pages():
    organization = OrganizationId(uuid=uuid7())
    link_uuid, pool_uuid = uuid7(), uuid7()
    queries = iter(
        (
            _Cursor(row=(1,)),
            _Cursor(rows=[_link_row(organization, link_uuid, pool_uuid)]),
        )
    )
    connection = _AsyncConnection(lambda _query, _params: next(queries))

    result = await PostgresLinkRepository(connection).list(
        organization, page=2, page_size=10, pool_id=PoolId(uuid=pool_uuid)
    )

    assert result.total == 1 and result.page == 2 and result.page_size == 10
    assert result.items[0].id == LinkId(uuid=link_uuid)
    assert result.items[0].pool_id == PoolId(uuid=pool_uuid)
    assert str(result.items[0].id) == f"lnk_{link_uuid.hex}"
    assert connection.calls[0][1] == (organization.uuid, pool_uuid)
    assert connection.calls[1][1] == (organization.uuid, pool_uuid, 10, 10)


@pytest.mark.asyncio
async def test_access_repository_maps_shared_canonical_organization_id():
    organization_id = OrganizationId(uuid=uuid7())
    connection = _AsyncConnection(
        lambda _query, _params: _Cursor(row=(organization_id.uuid, "Example", True))
    )

    organization = await PostgresOrganizationRepository(connection).find(
        "https://identity.example", organization_id
    )

    assert organization is not None
    assert organization.id == organization_id
    assert str(organization.id).startswith("org_")
    assert connection.calls[0][1] == ("https://identity.example", organization_id.uuid)


@pytest.mark.asyncio
async def test_public_repository_exposes_only_the_public_link_projection():
    link_uuid = uuid7()
    connection = _AsyncConnection(
        lambda _query, _params: _Cursor(row=(link_uuid, "abc123", None, True))
    )

    result = await PostgresLinkRepository(connection).public("abc123")

    assert result == PublicLinkDto(
        id=LinkId(uuid=link_uuid),
        short_code="abc123",
        destination_url=None,
        is_active=True,
    )
    assert {item.name for item in fields(PublicLinkDto)} == {
        "id",
        "short_code",
        "destination_url",
        "is_active",
    }


@pytest.mark.asyncio
async def test_create_conflict_rolls_back_savepoint_and_maps_the_named_constraint(
    monkeypatch: pytest.MonkeyPatch,
):
    error = UniqueViolation("duplicate public code")
    monkeypatch.setattr(
        UniqueViolation,
        "diag",
        property(lambda _self: SimpleNamespace(constraint_name="uq_links_short_code")),
    )

    def execute(_query: str, _params: tuple[object, ...]) -> _Cursor:
        raise error

    connection = _AsyncConnection(execute)
    organization = OrganizationId(uuid=uuid7())

    with pytest.raises(LinkConflictError, match="abc123"):
        await PostgresLinkRepository(connection).create(
            organization, LinkDraft("https://example.org", short_code="abc123")
        )

    assert len(connection.savepoints) == 1
    assert connection.savepoints[0].exit_error is UniqueViolation


@pytest.mark.asyncio
async def test_create_does_not_translate_unrelated_unique_constraints(
    monkeypatch: pytest.MonkeyPatch,
):
    error = UniqueViolation("duplicate unrelated value")
    monkeypatch.setattr(
        UniqueViolation,
        "diag",
        property(lambda _self: SimpleNamespace(constraint_name="other_constraint")),
    )

    def execute(_query: str, _params: tuple[object, ...]) -> _Cursor:
        raise error

    connection = _AsyncConnection(execute)

    with pytest.raises(UniqueViolation):
        await PostgresLinkRepository(connection).create(
            OrganizationId(uuid=uuid7()), LinkDraft("https://example.org", short_code="abc123")
        )

    assert connection.savepoints[0].exit_error is UniqueViolation


class _SyncScope:
    def __init__(self) -> None:
        self.exit_args: tuple[object, ...] | None = None

    def __enter__(self) -> _SyncScope:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    @contextmanager
    def transaction(self) -> Generator[None]:
        yield


class _Catalog:
    def __init__(
        self,
        *,
        history: tuple[tuple[Any, ...], ...] = (),
        rls: bool = True,
        history_exists: bool | None = None,
    ) -> None:
        self.history = history
        self.rls_enabled = rls
        self.history_exists = bool(history) if history_exists is None else history_exists
        self.marker = {
            "provider": "plazia-postgres-v1",
            "owner": "salyvinagre/plazia-links",
            "environment": "fixture",
            "roles": {"links_app": "links_app", "links_worker": "links_worker"},
        }

    def __enter__(self) -> _Catalog:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def transaction(self) -> _SyncScope:
        return _SyncScope()

    def execute(self, query: str, params: tuple[object, ...] = ()) -> _CatalogResult:
        _ = params
        revision = next((row[0] for row in reversed(self.history) if row[3] != "SCHEMA"), "1")
        statistics = int(revision) >= 3
        pixels = int(revision) >= 5
        if "shobj_description" in query:
            return _CatalogResult([(json.dumps(self.marker),)])
        if "AS owner_drift" in query or "AS private_access" in query:
            return _CatalogResult([(False,)])
        if (
            "AS pool_management" in query
            or "AS statistics_ready" in query
            or "AS pixels_ready" in query
        ):
            return _CatalogResult([(True,)])
        if "FROM pg_catalog.pg_constraint" in query:
            return _CatalogResult(
                [
                    (
                        name,
                        *value[:-2],
                        "r" if revision == "1" and name == "fk_links_pool_organization" else "c",
                        True,
                    )
                    for name, value in schema_module._DELETION_FKS.items()
                    if statistics or name != "fk_statistics_link_organization"
                ]
            )
        if "pg_catalog.pg_policy" in query:
            policies = SchemaAuthority._policies(
                self.marker["roles"]["links_worker"], statistics=statistics, pixels=pixels
            )
            return _CatalogResult(
                [(table, name, *value) for (table, name), value in policies.items()]
            )
        if "p.prosrc" in query:
            return _CatalogResult(
                [
                    (schema, name, *value)
                    for (schema, name), value in schema_module._FUNCTION_SECURITY.items()
                    if statistics or name != "record_visit"
                    if pixels or name not in {"resolve_public_pixel", "record_pixel_request"}
                ]
            )
        if "pg_catalog.pg_roles" in query:
            return _CatalogResult(
                [
                    (role, True, False, False, False, False, False, False)
                    for role in self.marker["roles"].values()
                ]
            )
        if "to_regclass" in query:
            table = "links_migrations.flyway_schema_history" if self.history_exists else None
            return _CatalogResult([(table,)])
        if "links_migrations.flyway_schema_history" in query:
            if "type IS DISTINCT FROM 'SCHEMA'" in query:
                return _CatalogResult(
                    [
                        (
                            *record,
                            next(
                                (
                                    row[4]
                                    for row in schema_module._EXPECTED_HISTORY
                                    if row[0] == record[0]
                                ),
                                0,
                            ),
                        )
                        for record in self.history
                        if record[3] != "SCHEMA"
                    ]
                )
            return _CatalogResult(list(self.history))
        if "pg_catalog.pg_class" in query:
            if "c.relrowsecurity" in query:
                names = (
                    "access.organizations",
                    "links.links",
                    "links.pools",
                    "links.subscriptions",
                    "platform.activation_emails",
                    "platform.audit_events",
                    "platform.command_receipts",
                )
                return _CatalogResult(
                    [
                        (name,)
                        for name in (
                            *names,
                            *(["links.statistics"] if statistics else []),
                            *(["links.pixels"] if pixels else []),
                        )
                        if self.rls_enabled or name != "links.links"
                    ]
                )
            names = (
                "access.organizations",
                "links.links",
                "links.pools",
                "links.subscriptions",
                "platform.activation_emails",
                "platform.audit_events",
                "platform.command_receipts",
                "links_migrations.flyway_schema_history",
            )
            return _CatalogResult(
                [
                    (name,)
                    for name in (
                        *names,
                        *(schema_module._STATISTICS_TABLES if statistics else []),
                        *(["links.pixels"] if pixels else []),
                    )
                ]
            )
        if "pg_catalog.pg_proc" in query:
            return _CatalogResult(
                [
                    ("links", "resolve_public_link"),
                    ("links", "subscribe_reserved_link"),
                    ("links", "ready_subscriptions"),
                    ("platform", "current_organization_id"),
                ]
            )
        if "pg_catalog.pg_namespace" in query:
            if not self.history_exists:
                return _CatalogResult([])
            return _CatalogResult(
                [(name,) for name in ("access", "links", "platform", "links_migrations")]
            )
        return _CatalogResult([])


class _CatalogResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


_VERSION_ONE = ("1", "V1__link_pools.sql", True, "SQL")
_CURRENT_HISTORY = tuple(row[:4] for row in schema_module._EXPECTED_HISTORY)
_FLYWAY_SCHEMA_ROW = (None, "<< Flyway Schema Creation >>", True, "SCHEMA")


def _catalog(monkeypatch: pytest.MonkeyPatch, value: _Catalog) -> None:
    monkeypatch.setattr(schema_module.psycopg, "connect", lambda *_args, **_kwargs: value)


def test_schema_authority_admits_empty_target_and_current_flyway_schema(monkeypatch):
    empty = _Catalog()
    _catalog(monkeypatch, empty)
    authority = SchemaAuthority("postgresql://db.example/links")
    authority.prepare()

    current = _Catalog(history=(_FLYWAY_SCHEMA_ROW, *_CURRENT_HISTORY))
    _catalog(monkeypatch, current)
    status = authority.finish()

    assert status.revision == "5"
    assert "links_migrations.flyway_schema_history" in status.tables


@pytest.mark.parametrize("revision", (1, 2, 3, 4))
def test_schema_authority_admits_packaged_prefix_for_upgrade_but_not_runtime(monkeypatch, revision):
    _catalog(monkeypatch, _Catalog(history=_CURRENT_HISTORY[:revision]))
    authority = SchemaAuthority("postgresql://db.example/links")
    authority.prepare()
    with pytest.raises(SchemaError, match="history"):
        authority.check()


def test_schema_authority_keeps_role_bindings_with_each_transaction(monkeypatch):
    outer = _Catalog(history=_CURRENT_HISTORY)
    inner = _Catalog(history=_CURRENT_HISTORY)
    inner.marker["roles"] = {
        "links_app": "scoped_links_app",
        "links_worker": "scoped_links_worker",
    }
    connections = iter((outer, inner))
    monkeypatch.setattr(schema_module.psycopg, "connect", lambda *_a, **_k: next(connections))
    authority = SchemaAuthority("postgresql://db.example/links")
    execute = outer.execute

    def overlapping_check(query, params=()):
        if "FROM pg_catalog.pg_roles" in query:
            assert authority.finish().revision == "5"
        return execute(query, params)

    monkeypatch.setattr(outer, "execute", overlapping_check)

    assert authority.finish().revision == "5"


@pytest.mark.parametrize(
    ("history", "rls"),
    [
        ((("2", "V2__later.sql", True, "SQL"),), True),
        ((_VERSION_ONE,), False),
        ((("1", "V1__link_pools.sql", True, "BASELINE"),), True),
    ],
)
def test_schema_authority_rejects_unexpected_history_and_missing_rls(
    monkeypatch: pytest.MonkeyPatch,
    history: tuple[tuple[Any, ...], ...],
    rls: bool,
):
    _catalog(monkeypatch, _Catalog(history=history, rls=rls))

    with pytest.raises(SchemaError):
        SchemaAuthority("postgresql://db.example/links").check()


@pytest.mark.parametrize(
    "changes",
    [
        {"owner": "example/other"},
        {"provider": "other"},
        {"environment": ""},
        {"roles": {"links_app": "bad;role", "links_worker": "worker"}},
        {"roles": {"links_app": "same", "links_worker": "same"}},
        {"roles": {"links_app": "app"}},
    ],
)
def test_schema_authority_rejects_invalid_provider_binding(monkeypatch, changes):
    catalog = _Catalog()
    catalog.marker.update(changes)
    _catalog(monkeypatch, catalog)
    with pytest.raises(SchemaError, match="role binding"):
        SchemaAuthority("postgresql://db.example/links").prepare()


@pytest.mark.asyncio
async def test_database_scope_sets_transaction_mode_and_shared_tenant_context(monkeypatch):
    organization = OrganizationId(uuid=uuid7())
    connection = _AsyncConnection(lambda _query, _params: _Cursor())
    opened: dict[str, Any] = {}

    @asynccontextmanager
    async def open_connection(source: object, **kwargs: object):
        opened["source"] = source
        opened.update(kwargs)
        yield connection

    monkeypatch.setattr(
        database_module.PostgresConnectionContext,
        "open",
        staticmethod(open_connection),
    )
    database = PostgresDatabase("postgresql://db.example/links", pooled=False)

    async with database.scope(organization, readonly=False):
        pass

    assert opened["organization_id"] == str(organization)
    assert opened["configuration"].organization_id_setting == "plazia.organization_id"
    assert any(query == "SET TRANSACTION READ WRITE" for query, _ in connection.calls)
    assert any(params == (str(organization), True) for _, params in connection.calls)


class _CommandScope:
    def __init__(self) -> None:
        self.exit_calls: list[tuple[object, ...]] = []
        self.failure: BaseException | None = None

    async def __aenter__(self) -> _CommandScope:
        return self

    async def __aexit__(self, *args: object) -> bool:
        self.exit_calls.append(args)
        if self.failure is not None:
            raise self.failure
        return False


class _CommandDatabase:
    def __init__(self) -> None:
        self.organization_id: OrganizationId | None = None
        self.readonly: bool | None = None
        self.scope_value = _CommandScope()

    def scope(self, organization_id: OrganizationId | None = None, *, readonly: bool = True):
        self.organization_id = organization_id
        self.readonly = readonly
        return self.scope_value


@pytest.mark.asyncio
async def test_command_uow_binds_actor_organization_and_commits_or_rolls_back():
    organization = OrganizationId(uuid=uuid7())
    actor = SimpleNamespace(organization_id=organization)
    database = _CommandDatabase()
    factory = PostgresUowFactory(database)  # type: ignore[arg-type]
    uow = await factory.start(SimpleNamespace(command=SimpleNamespace(actor=actor)))

    async with uow:
        assert uow.scope is database.scope_value
        await uow.commit()

    assert database.organization_id == organization and database.readonly is False
    assert database.scope_value.exit_calls == [(None, None, None)]
    assert uow.scope is None


@pytest.mark.asyncio
async def test_command_uow_rolls_back_on_exit_and_surfaces_commit_failure():
    database = _CommandDatabase()
    uow = await PostgresUowFactory(database).start(SimpleNamespace(command=None))  # type: ignore[arg-type]

    async with uow:
        pass

    assert len(database.scope_value.exit_calls) == 1
    assert database.scope_value.exit_calls[0][0] is database_module._RollbackError

    failed_scope = _CommandScope()
    failed_scope.failure = RuntimeError("commit failed")
    database.scope_value = failed_scope
    failed_uow = await PostgresUowFactory(database).start(SimpleNamespace(command=None))  # type: ignore[arg-type]
    await failed_uow.__aenter__()
    with pytest.raises(RuntimeError, match="commit failed"):
        await failed_uow.commit()
    await failed_uow.__aexit__(RuntimeError, RuntimeError("commit failed"), None)
    assert failed_uow.scope is None
    assert len(failed_scope.exit_calls) == 1


@pytest.mark.asyncio
async def test_command_uow_closes_scope_after_rollback_failure():
    database = _CommandDatabase()
    database.scope_value.failure = RuntimeError("rollback failed")
    uow = await PostgresUowFactory(database).start(SimpleNamespace(command=None))  # type: ignore[arg-type]
    await uow.__aenter__()

    with pytest.raises(RuntimeError, match="rollback failed"):
        await uow.__aexit__(None, None, None)

    assert uow.scope is None


@pytest.mark.parametrize(
    ("role", "elevated", "runtime", "allowed"),
    [
        ("links_app", False, "app", True),
        ("links_worker", False, "worker", True),
        ("postgres", False, "app", False),
        ("links_worker", False, "app", False),
        ("links_app", True, "app", False),
    ],
)
def test_runtime_admission_rejects_owner_credentials_and_inherited_bypass(
    monkeypatch, role, elevated, runtime, allowed
):
    class Catalog(_Catalog):
        def execute(self, query, params=()):
            if "SELECT current_user" in query:
                return _CatalogResult([(role, elevated)])
            return super().execute(query, params)

    _catalog(monkeypatch, Catalog(history=_CURRENT_HISTORY))
    authority = SchemaAuthority("postgresql://db/links")
    if allowed:
        assert authority.check(runtime=runtime).revision == "5"
    else:
        with pytest.raises(SchemaError, match="dedicated role"):
            authority.check(runtime=runtime)
