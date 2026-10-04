"""PostgreSQL 18 acceptance for tenant isolation and activation delivery."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import pytest
from psycopg import AsyncConnection
from psycopg.errors import InsufficientPrivilege, ReadOnlySqlTransaction
from shared_identity.canonical_ids import OrganizationId
from shared_kernel.actor_context import ActorContext
from shared_kernel.contacts import NormalizedEmail
from shared_kernel.operation_context import OperationContext
from shared_persistence import (
    PostgresConnectionContext,
    PostgresSessionConfiguration,
    configure_postgres_transaction,
)

from app.contexts.links.domain.link import (
    LinkConflictError,
    LinkDisabledError,
    LinkDraft,
    LinkNotFoundError,
    LinkPatch,
    PublicCode,
)
from app.kernel.ids import LinkId
from app.platform.database import PostgresDatabase
from app.platform.persistence.schema import SchemaAuthority

_SESSION_CONFIGURATION = PostgresSessionConfiguration(
    search_path=("links", "access", "platform", "public"),
    organization_id_setting="plazia.organization_id",
)


@dataclass(frozen=True, slots=True)
class _DatabaseUrls:
    app: str
    worker: str
    owner: str


@dataclass(frozen=True, slots=True)
class _Invocation:
    actor_context: ActorContext
    operation_context: OperationContext


class _AbortWriteError(Exception):
    pass


@pytest.fixture(scope="module")
def postgres_urls() -> _DatabaseUrls:
    values = (
        os.environ.get("POSTGRES_TEST_URL"),
        os.environ.get("POSTGRES_WORKER_TEST_URL"),
        os.environ.get("POSTGRES_OWNER_TEST_URL"),
    )
    if not all(values):
        pytest.skip(
            "POSTGRES_TEST_URL, POSTGRES_WORKER_TEST_URL and POSTGRES_OWNER_TEST_URL "
            "must point to the isolated Flyway-migrated PostgreSQL 18 database"
        )
    urls = _DatabaseUrls(app=values[0], worker=values[1], owner=values[2])  # type: ignore[arg-type]
    assert SchemaAuthority(urls.owner).check().revision == "4"
    return urls


@pytest.mark.slow
async def test_statistics_are_atomic_private_readonly_and_removed_with_links(postgres_urls):
    database = PostgresDatabase(postgres_urls.app)
    organization, other = OrganizationId.new(), OrganizationId.new()
    code = PublicCode.generate()
    try:
        await _bind_organization(postgres_urls.owner, "https://identity.example.test", organization)
        await _bind_organization(postgres_urls.owner, "https://identity.example.test", other)
        async with database.scope(organization, readonly=False) as scope:
            pool = await scope.links.reserve(
                organization, "Statistics", (code, PublicCode.generate())
            )
            link, unvisited = (await scope.links.list(organization, 1, 20, pool.id)).items
            code = link.short_code

        async def record():
            async with database.scope(None, readonly=False) as scope:
                await scope.links.record_visit(link.id, code, "waiting")

        await asyncio.gather(*(record() for _ in range(24)))
        with pytest.raises(_AbortWriteError):
            async with database.scope(None, readonly=False) as scope:
                await scope.links.record_visit(link.id, code, "waiting")
                raise _AbortWriteError
        async with database.scope(None, readonly=False) as scope:
            await scope.links.record_visit(link.id, PublicCode.generate(), "waiting")
            await scope.links.record_visit(link.id, code, "redirect")
            for _ in range(2):
                await scope.links.subscribe(link.id, NormalizedEmail("subscriber@example.test"))
            await scope.links.subscribe(link.id, NormalizedEmail("second@example.test"))
            await scope.links.subscribe(unvisited.id, NormalizedEmail("subscriber@example.test"))
        async with database.scope(organization) as scope:
            stats = await scope.links.statistics(organization, (organization, pool.id, link.id))
            for value in stats.values():
                assert (value.redirects, value.waiting_views) == (0, 24)
                assert value.subscribers == (2 if value is stats[link.id] else 3)
                assert value.tracked_from <= value.last_visited_at <= value.as_of
            value = (await scope.links.statistics(organization, (unvisited.id,)))[unvisited.id]
            assert (value.waiting_views, value.subscribers, value.last_visited_at) == (0, 1, None)
        async with database.scope(other) as scope:
            value = (await scope.links.statistics(other, (other, link.id)))[link.id]
            assert (value.waiting_views, value.subscribers) == (0, 0)
        with pytest.raises(ReadOnlySqlTransaction):
            async with database.scope(None) as scope:
                await scope.links.record_visit(link.id, code, "waiting")

        async with await AsyncConnection.connect(postgres_urls.app) as connection:
            await configure_postgres_transaction(
                connection, organization_id=str(other), configuration=_SESSION_CONFIGURATION
            )
            assert (
                await (
                    await connection.execute(
                        "SELECT (SELECT count(*) FROM links.statistics), "
                        "(SELECT count(*) FROM links.subscriptions)"
                    )
                ).fetchone()
            ) == (0, 0)
        for url, statement in (
            (postgres_urls.app, "DELETE FROM links.statistics"),
            (postgres_urls.app, "UPDATE links.statistics SET redirects=9000"),
            (postgres_urls.app, "SELECT email FROM links.subscriptions"),
            (postgres_urls.worker, "SELECT * FROM links.statistics"),
            (postgres_urls.worker, "SELECT links.record_visit(%s,%s,'waiting')"),
        ):
            with pytest.raises(InsufficientPrivilege):
                async with await AsyncConnection.connect(url) as connection:
                    await connection.execute(
                        statement, (link.id.uuid, code) if "%s" in statement else None
                    )

        # A cancelled, row-blocked update must release the connection and not count.
        async with await AsyncConnection.connect(postgres_urls.owner) as owner:
            await owner.execute("SELECT * FROM links.statistics FOR UPDATE")
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.25):
                    await record()
        await record()
        async with database.scope(organization, readonly=False) as scope:
            assert (await scope.links.statistics(organization, (link.id,)))[
                link.id
            ].waiting_views == 25
            await scope.links.delete_pool(organization, pool.id)
        async with database.scope(organization) as scope:
            value = (await scope.links.statistics(organization, (organization,)))[organization]
            assert (value.waiting_views, value.subscribers) == (0, 0)
        async with await AsyncConnection.connect(postgres_urls.owner) as owner:
            assert (
                await (
                    await owner.execute(
                        "SELECT count(*) FROM links.statistics WHERE organization_id=%s",
                        (organization.uuid,),
                    )
                ).fetchone()
            )[0] == 0
    finally:
        await database.close()
        await _cleanup(postgres_urls.owner, (organization, other))


@pytest.mark.slow
async def test_activation_outbox_is_atomic_private_and_tenant_scoped(
    postgres_urls: _DatabaseUrls,
) -> None:
    database = PostgresDatabase(postgres_urls.app)
    organization_id = OrganizationId.new()
    other_organization_id = OrganizationId.new()
    issuer = "https://identity.example.test"
    code = PublicCode.generate()
    email = NormalizedEmail("reserved-link@example.test")
    link_id: LinkId | None = None

    try:
        await _bind_organization(postgres_urls.owner, issuer, organization_id)
        await _bind_organization(postgres_urls.owner, issuer, other_organization_id)

        async with database.scope(organization_id, readonly=False) as scope:
            pool = await scope.links.reserve(organization_id, "activation pool", (code,))
            page = await scope.links.list(organization_id, 1, 10, pool.id)
            assert len(page.items) == 1
            link = page.items[0]
            link_id = link.id
            assert link.destination_url is None
            assert link.pool_id == pool.id

            await scope.links.subscribe(link.id, email)
            await scope.links.subscribe(link.id, email)

        async with database.scope(None, readonly=True) as scope:
            public_link = await scope.links.public(code)
            assert public_link.id == link_id
            assert public_link.destination_url is None
            assert not hasattr(public_link, "notes")

        patch = LinkPatch(
            fields=frozenset({"destination_url"}),
            destination_url="https://destination.example.test/ready",
        )
        invocation = _invocation()
        with pytest.raises(_AbortWriteError):
            async with database.scope(organization_id, readonly=False) as scope:
                await scope.links.get(organization_id, link.id, lock=True)
                await scope.links.update(organization_id, link.id, patch)
                await scope.links.ready_subscriptions(organization_id, link.id)
                await scope.links.audit(organization_id, "update", (link.id,), invocation)
                raise _AbortWriteError

        async with database.scope(organization_id, readonly=True) as scope:
            still_reserved = await scope.links.get(organization_id, link.id)
            assert still_reserved.destination_url is None
        assert await _ready_emails(postgres_urls.worker, organization_id, link.id) == ()

        async with database.scope(organization_id, readonly=False) as scope:
            await scope.links.get(organization_id, link.id, lock=True)
            active = await scope.links.update(organization_id, link.id, patch)
            await scope.links.ready_subscriptions(organization_id, active.id)
            await scope.links.audit(organization_id, "update", (active.id,), invocation)
            assert active.destination_url == patch.destination_url

        jobs = await _ready_emails(postgres_urls.worker, organization_id, link.id)
        assert jobs == ((str(email), patch.destination_url, 0),)
        assert await _api_pii_privileges(postgres_urls.app, organization_id) == (False, False)

        async with database.scope(other_organization_id, readonly=True) as scope:
            with pytest.raises(LinkNotFoundError):
                await scope.links.get(other_organization_id, link.id)

        async with database.scope(organization_id, readonly=False) as scope:
            await scope.links.update(
                organization_id,
                link.id,
                LinkPatch(fields=frozenset({"is_active"}), is_active=False),
            )
            with pytest.raises(LinkDisabledError):
                await scope.links.subscribe(link.id, NormalizedEmail("another@example.test"))
        assert await _ready_emails(postgres_urls.worker, organization_id, link.id) == ()

        audit = await _audit_rows(postgres_urls.owner, organization_id, link.id)
        assert audit == (("update", "test-actor", "user", "request-1", "correlation-1"),)
    finally:
        await database.close()
        await _cleanup(postgres_urls.owner, (organization_id, other_organization_id))


@pytest.mark.slow
async def test_subscription_and_activation_serialize_on_the_link_row(
    postgres_urls: _DatabaseUrls,
) -> None:
    database = PostgresDatabase(postgres_urls.app)
    organization_id = OrganizationId.new()
    issuer = "https://identity.example.test"
    code = PublicCode.generate()
    link_id: LinkId | None = None
    acquired = asyncio.Event()
    release = asyncio.Event()
    activation_attempting = asyncio.Event()

    try:
        await _bind_organization(postgres_urls.owner, issuer, organization_id)
        async with database.scope(organization_id, readonly=False) as scope:
            pool = await scope.links.reserve(organization_id, "locking pool", (code,))
            link_id = (await scope.links.list(organization_id, 1, 10, pool.id)).items[0].id

        async def subscribe_first() -> None:
            async with database.scope(organization_id, readonly=False) as scope:
                public_link = await scope.links.public(code, lock=True)
                assert public_link.destination_url is None
                await scope.links.subscribe(
                    public_link.id,
                    NormalizedEmail("serialized@example.test"),
                )
                acquired.set()
                await release.wait()

        async def activate_second() -> None:
            await acquired.wait()
            async with database.scope(organization_id, readonly=False) as scope:
                activation_attempting.set()
                await scope.links.get(organization_id, link_id, lock=True)
                updated = await scope.links.update(
                    organization_id,
                    link_id,
                    LinkPatch(
                        fields=frozenset({"destination_url"}),
                        destination_url="https://destination.example.test/serialized",
                    ),
                )
                await scope.links.ready_subscriptions(organization_id, updated.id)

        subscribe_task = asyncio.create_task(subscribe_first())
        activation_task = asyncio.create_task(activate_second())
        await asyncio.wait_for(activation_attempting.wait(), timeout=5)
        done, _ = await asyncio.wait({activation_task}, timeout=0.05)
        assert not done, "activation passed the public subscription row lock"
        release.set()
        await asyncio.wait_for(asyncio.gather(subscribe_task, activation_task), timeout=5)

        assert await _ready_emails(postgres_urls.worker, organization_id, link_id) == (
            ("serialized@example.test", "https://destination.example.test/serialized", 0),
        )
    finally:
        release.set()
        await database.close()
        await _cleanup(postgres_urls.owner, (organization_id,))


@pytest.mark.slow
async def test_code_collisions_rollback_savepoints_without_poisoning_the_command(
    postgres_urls: _DatabaseUrls,
) -> None:
    database = PostgresDatabase(postgres_urls.app, pooled=False)
    organization_id = OrganizationId.new()
    code = PublicCode.generate()

    try:
        await _bind_organization(
            postgres_urls.owner,
            "https://identity.example.test",
            organization_id,
        )
        async with database.scope(organization_id, readonly=False) as scope:
            pool = await scope.links.reserve(organization_id, "collision pool", (code,))
            before = await scope.links.pools(organization_id, 1, 20)
            with pytest.raises(LinkConflictError):
                await scope.links.reserve(organization_id, "duplicate pool", (code,))
            after = await scope.links.pools(organization_id, 1, 20)
            assert after.total == before.total == 1

            with pytest.raises(LinkConflictError):
                await scope.links.create(
                    organization_id,
                    LinkDraft(
                        destination_url="https://destination.example.test/collision",
                        short_code=code,
                    ),
                )
            assert (await scope.links.get_pool(organization_id, pool.id)).size == 1
            assert (await scope.links.list(organization_id, 1, 20)).total == 1
    finally:
        await database.close()
        await _cleanup(postgres_urls.owner, (organization_id,))


async def _bind_organization(
    owner_url: str,
    issuer: str,
    organization_id: OrganizationId,
) -> None:
    async with await AsyncConnection.connect(owner_url) as connection:
        async with connection.transaction():
            await connection.execute(
                """
                INSERT INTO access.organizations (issuer, organization_id, name, is_active)
                VALUES (%s, %s, 'Integration test', true)
                """,
                (issuer, organization_id.uuid),
            )


async def _cleanup(owner_url: str, organizations: tuple[OrganizationId, ...]) -> None:
    if not organizations:
        return
    ids = [organization_id.uuid for organization_id in organizations]
    async with await AsyncConnection.connect(owner_url) as connection:
        async with connection.transaction():
            await connection.execute(
                "DELETE FROM platform.audit_events WHERE organization_id = ANY(%s)",
                (ids,),
            )
            await connection.execute(
                "DELETE FROM links.links WHERE organization_id = ANY(%s)",
                (ids,),
            )
            await connection.execute(
                "DELETE FROM links.pools WHERE organization_id = ANY(%s)",
                (ids,),
            )
            await connection.execute(
                "DELETE FROM access.organizations WHERE organization_id = ANY(%s)",
                (ids,),
            )


async def _ready_emails(
    worker_url: str,
    organization_id: OrganizationId,
    link_id: LinkId,
) -> tuple[tuple[str, str, int], ...]:
    async with PostgresConnectionContext.open(
        worker_url,
        normalize_connection_url=_normalize_postgres_url,
        configuration=_SESSION_CONFIGURATION,
    ) as connection:
        async with connection.transaction():
            await connection.execute("SET TRANSACTION READ ONLY")
            await configure_postgres_transaction(
                connection,
                organization_id=str(organization_id),
                configuration=_SESSION_CONFIGURATION,
            )
            cursor = await connection.execute(
                """
                SELECT s.email, l.destination_url, j.attempts
                FROM platform.activation_emails AS j
                JOIN links.subscriptions AS s
                  ON s.organization_id = j.organization_id
                 AND s.link_id = j.link_id
                 AND s.id = j.subscription_id
                JOIN links.links AS l
                  ON l.organization_id = j.organization_id AND l.id = j.link_id
                WHERE j.organization_id = %s
                  AND j.link_id = %s
                  AND j.sent_at IS NULL
                  AND j.attempts < 5
                  AND j.next_attempt_at <= clock_timestamp()
                  AND l.is_active
                  AND l.destination_url IS NOT NULL
                ORDER BY j.created_at, j.id
                """,
                (organization_id.uuid, link_id.uuid),
            )
            rows = await cursor.fetchall()
    return tuple((row[0], row[1], row[2]) for row in rows)


async def _api_pii_privileges(
    app_url: str,
    organization_id: OrganizationId,
) -> tuple[bool, bool]:
    async with PostgresConnectionContext.open(
        app_url,
        normalize_connection_url=_normalize_postgres_url,
        configuration=_SESSION_CONFIGURATION,
    ) as connection:
        async with connection.transaction():
            await connection.execute("SET TRANSACTION READ ONLY")
            await configure_postgres_transaction(
                connection,
                organization_id=str(organization_id),
                configuration=_SESSION_CONFIGURATION,
            )
            cursor = await connection.execute(
                """
                SELECT has_table_privilege(current_user, 'links.subscriptions', 'SELECT'),
                       has_table_privilege(current_user, 'platform.activation_emails', 'SELECT')
                """
            )
            row = await cursor.fetchone()
    return row[0], row[1]


async def _audit_rows(
    owner_url: str,
    organization_id: OrganizationId,
    link_id: LinkId,
) -> tuple[tuple[str, str, str, str, str | None], ...]:
    async with await AsyncConnection.connect(owner_url) as connection:
        async with connection.transaction():
            cursor = await connection.execute(
                """
                SELECT action, actor_id, actor_type, request_id, correlation_id
                FROM platform.audit_events
                WHERE organization_id = %s AND resource_type = 'link' AND resource_id = %s
                ORDER BY recorded_at
                """,
                (organization_id.uuid, link_id.uuid),
            )
            rows = await cursor.fetchall()
    return tuple(rows)


def _normalize_postgres_url(url: str) -> str:
    for scheme in ("postgres://", "postgresql+asyncpg://", "postgresql+psycopg://"):
        if url.startswith(scheme):
            return "postgresql://" + url[len(scheme) :]
    return url


def _invocation() -> _Invocation:
    return _Invocation(
        actor_context=ActorContext(actor_id="test-actor", actor_type="user"),
        operation_context=OperationContext(
            request_id="request-1",
            correlation_id="correlation-1",
            source_channel="integration-test",
        ),
    )
