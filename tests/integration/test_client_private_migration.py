"""Upgrade real V6 rows and receipts without changing their owner or retry lifetime."""

import hashlib
import json
import os
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from psycopg import Connection, errors, sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from shared_identity import OrganizationId
from shared_kernel import ActorContext, OperationContext, RequestContext

from app.contexts.access.domain.principal import Principal
from app.contexts.links.application.dto.links import LinkDto, PoolDto
from app.contexts.links.contracts import CreateLinkCommand, ReservePoolCommand
from app.contexts.links.domain.link import Entropy, IdempotencyConflictError, LinkDraft, Visibility
from app.kernel.ids import LinkId, PoolId
from app.platform.composition import Container
from app.platform.database import PostgresDatabase, PostgresUowFactory
from tests.support import FixtureAuthority

MIGRATIONS = Path(__file__).parents[2] / "app/platform/persistence/sql/migrations"


@pytest.fixture
def upgrade_database():
    url = os.environ.get("POSTGRES_OWNER_TEST_URL")
    if not url:
        pytest.skip("An isolated PostgreSQL owner with CREATEDB is required")
    name = "links_upgrade_" + uuid4().hex
    with Connection.connect(url, autocommit=True) as owner:
        marker = owner.execute(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
            "WHERE datname=current_database()"
        ).fetchone()[0]
        roles = json.loads(marker)["roles"]
        owner.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
        try:
            owner.execute(
                sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                    sql.Identifier(name), sql.Literal(marker)
                )
            )
            selected = make_conninfo(url, dbname=name)
            with Connection.connect(selected) as connection:
                # V1 grants history reads. Flyway itself is qualified separately; this
                # fixture executes the immutable SQL prefix and the upgrade transaction.
                connection.execute("CREATE SCHEMA links_migrations")
                connection.execute(
                    "CREATE TABLE links_migrations.flyway_schema_history (version text)"
                )
                for path in sorted(MIGRATIONS.glob("V[1-6]__*.sql")):
                    connection.execute(
                        path.read_text()
                        .replace("${appRole}", roles["links_app"])
                        .replace("${workerRole}", roles["links_worker"])
                    )
            app = urlsplit(os.environ["POSTGRES_TEST_URL"])._replace(path="/" + name).geturl()
            yield selected, app
        finally:
            owner.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@pytest.mark.slow
@pytest.mark.parametrize("corrupt", [False, True])
async def test_upgrade_preserves_private_receipts_and_exact_input(upgrade_database, corrupt):
    owner_url, app_url = upgrade_database
    org = OrganizationId.new()
    issuer = "https://identity.example.test"
    actor = Principal(
        issuer,
        "machine",
        "printer",
        org,
        frozenset({"pools:create", "links:create"}),
        9999999999,
        "jwt",
    )
    now = datetime.now(UTC)
    expires = now + timedelta(days=3)
    text = 'workload_private / café 漢字 😀 "quoted" \\ \t\nend'
    stored_pool, stored_link = PoolId.new(), LinkId.new()
    cases = []
    with Connection.connect(owner_url) as connection:
        connection.execute(
            "INSERT INTO access.organizations (issuer,organization_id,name,workloads) "
            "VALUES (%s,%s,'Printer',ARRAY['printer'])",
            (issuer, org.uuid),
        )
        connection.execute(
            "SELECT set_config('plazia.issuer', %s, true), "
            "set_config('plazia.client_id', %s, true)",
            (issuer, actor.client_id),
        )
        connection.execute(
            "INSERT INTO links.pools (id,organization_id,name,entropy,visibility) "
            "VALUES (%s,%s,%s,'high','workload_private')",
            (stored_pool.uuid, org.uuid, text),
        )
        connection.execute(
            "INSERT INTO links.links "
            "(id,organization_id,pool_id,short_code,entropy,visibility) "
            "VALUES (%s,%s,%s,%s,'high','workload_private')",
            (stored_link.uuid, org.uuid, stored_pool.uuid, "b" * 32),
        )
        # Preserve literal legacy words in user text; only the visibility field changes.
        for name in (None, text):
            for entropy in (None, Entropy.high):
                for visibility in (None, Visibility.client_private):
                    pool_id = PoolId.new()
                    for command, result in (
                        (
                            ReservePoolCommand(actor, 1, name, entropy, visibility),
                            PoolDto(pool_id, name, 1, now, Entropy.high, Visibility.client_private),
                        ),
                        (
                            CreateLinkCommand(
                                actor,
                                LinkDraft(
                                    "https://example.com/workload_private",
                                    title=name,
                                    notes=name,
                                    pool_id=pool_id if name else None,
                                    entropy=entropy,
                                    visibility=visibility,
                                ),
                            ),
                            LinkDto(
                                LinkId.new(),
                                "a" * 32,
                                "https://example.com/workload_private",
                                name,
                                name,
                                True,
                                now,
                                now,
                                pool_id if name else None,
                                Entropy.high,
                                Visibility.client_private,
                            ),
                        ),
                    ):
                        payload = asdict(command)
                        del payload["actor"]
                        policy = payload.get("draft", payload)
                        if visibility is not None:
                            policy["visibility"] = "workload_private"
                        fingerprint = hashlib.sha256(
                            json.dumps(payload, sort_keys=True, default=str).encode()
                        ).hexdigest()
                        snapshot = json.loads(json.dumps(asdict(result), default=str))
                        snapshot["visibility"] = "workload_private"
                        key = str(len(cases))
                        connection.execute(
                            "INSERT INTO platform.command_receipts "
                            "(organization_id,issuer,subject,client_id,action,key,"
                            "fingerprint,result,expires_at) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (
                                org.uuid,
                                issuer,
                                actor.subject,
                                actor.client_id,
                                type(command).__name__,
                                key,
                                fingerprint,
                                Jsonb({"value": snapshot}),
                                expires,
                            ),
                        )
                        cases.append((key, command, result))
        if corrupt:
            connection.execute(
                "UPDATE platform.command_receipts SET fingerprint=%s WHERE key='0'", ("0" * 64,)
            )
    if corrupt:
        with pytest.raises(errors.RaiseException, match="Cannot migrate a live private receipt"):
            with Connection.connect(owner_url) as connection:
                connection.execute((MIGRATIONS / "V7__client_private.sql").read_text())
        with Connection.connect(owner_url) as connection:
            assert connection.execute("SELECT workloads FROM access.organizations").fetchone()[
                0
            ] == ["printer"]
            assert connection.execute("SELECT DISTINCT visibility FROM links.links").fetchall() == [
                ("workload_private",)
            ]
        return
    with Connection.connect(owner_url) as connection:
        connection.execute((MIGRATIONS / "V7__client_private.sql").read_text())
        assert connection.execute("SELECT private_clients FROM access.organizations").fetchone()[
            0
        ] == ["printer"]
        assert connection.execute(
            "SELECT DISTINCT expires_at FROM platform.command_receipts"
        ).fetchall() == [(expires,)]
        assert connection.execute(
            "SELECT visibility, owner_issuer, owner_client FROM links.links"
        ).fetchone() == ("client_private", issuer, actor.client_id)

    database = PostgresDatabase(app_url)
    try:
        async with database.scope(org, actor=actor) as scope:
            row = await scope.links.get(org, stored_link)
            assert row.pool_id == stored_pool and row.short_code == "b" * 32
            assert row.visibility is Visibility.client_private
        bus, _ = Container.buses(database, PostgresUowFactory(database), FixtureAuthority())
        for key, command, result in cases:
            context = RequestContext(
                ActorContext("machine", "machine"), OperationContext("upgrade", idempotency_key=key)
            )
            replay = await bus.dispatch(command, context=context)
            assert replay.replayed and replay.value == result
            changed = (
                replace(command, size=2)
                if isinstance(command, ReservePoolCommand)
                else replace(command, draft=replace(command.draft, notes="changed"))
            )
            with pytest.raises(IdempotencyConflictError):
                await bus.dispatch(changed, context=context)
        with Connection.connect(owner_url) as connection:
            assert connection.execute("SELECT count(*) FROM links.links").fetchone()[0] == 1
            assert (
                connection.execute("SELECT count(*) FROM platform.audit_events").fetchone()[0] == 0
            )
            connection.execute(
                "UPDATE platform.command_receipts "
                "SET expires_at=clock_timestamp()-interval '1 second'"
            )
        with pytest.raises(IdempotencyConflictError):
            await bus.dispatch(command, context=context)
    finally:
        await database.close()
