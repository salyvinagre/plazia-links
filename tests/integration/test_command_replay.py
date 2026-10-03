"""Concurrent durable replay through the real shared command bus and PostgreSQL UoW."""

import asyncio

import pytest
from shared_identity import OrganizationId
from shared_kernel import ActorContext, OperationContext, RequestContext
from shared_kernel.contacts import NormalizedEmail

from app.contexts.access.domain.principal import Principal
from app.contexts.links.contracts import (
    DeleteLinksCommand,
    DeletePoolCommand,
    RenamePoolCommand,
    ReservePoolCommand,
    UpdateLinkCommand,
)
from app.contexts.links.domain.link import IdempotencyConflictError, LinkNotFoundError, LinkPatch
from app.platform.composition import build_buses
from app.platform.database import PostgresDatabase, PostgresUowFactory
from tests.integration.test_postgres_links import _bind_organization, _cleanup, _ready_emails
from tests.integration.test_postgres_links import postgres_urls as postgres_urls
from tests.support import FixtureAuthority


@pytest.mark.slow
async def test_same_key_concurrency_produces_one_pool_and_original_result(postgres_urls):
    org = OrganizationId.new()
    issuer = "https://identity.example.test"
    database = PostgresDatabase(postgres_urls.app)
    actor = Principal(
        issuer, "subject", "client", org, frozenset({"links:create"}), 9999999999, "jwt-id"
    )
    context = RequestContext(
        ActorContext("subject", "user"), OperationContext("req-1", idempotency_key="reserve-1")
    )
    try:
        await _bind_organization(postgres_urls.owner, issuer, org)
        bus, _ = build_buses(database, PostgresUowFactory(database), FixtureAuthority())
        command = ReservePoolCommand(actor, 3, "Launch")
        first, second = await asyncio.wait_for(
            asyncio.gather(
                bus.dispatch(command, context=context), bus.dispatch(command, context=context)
            ),
            timeout=5,
        )
        assert first.value == second.value and first.replayed != second.replayed
        async with database.scope(org) as scope:
            assert (await scope.links.pools(org, 1, 10)).total == 1
            assert (await scope.links.list(org, 1, 10)).total == 3
        with pytest.raises(IdempotencyConflictError):
            await bus.dispatch(ReservePoolCommand(actor, 4, "Launch"), context=context)
        later = await bus.dispatch(command, context=context)
        assert later.value == first.value and later.replayed
    finally:
        await database.close()
        await _cleanup(postgres_urls.owner, (org,))


@pytest.mark.slow
async def test_pool_management_and_bulk_delete_are_tenant_scoped_and_durable(postgres_urls):
    org, foreign = OrganizationId.new(), OrganizationId.new()
    issuer = "https://identity.example.test"
    database = PostgresDatabase(postgres_urls.app)
    actor = Principal(
        issuer,
        "subject",
        "client",
        org,
        frozenset({"links:create", "links:update", "links:delete"}),
        9999999999,
        "jwt-id",
    )
    other_actor = Principal(
        issuer, "subject", "client", foreign, actor.scopes, 9999999999, "jwt-id"
    )

    def context(key):
        return RequestContext(
            ActorContext("subject", "user"), OperationContext("request", idempotency_key=key)
        )

    try:
        for id in (org, foreign):
            await _bind_organization(postgres_urls.owner, issuer, id)
        bus, _ = build_buses(database, PostgresUowFactory(database), FixtureAuthority())
        pool = (
            await bus.dispatch(ReservePoolCommand(actor, 3, "Launch"), context=context("reserve"))
        ).value
        other = (
            await bus.dispatch(ReservePoolCommand(actor, 1, "Keep"), context=context("keep"))
        ).value
        foreign_pool = (
            await bus.dispatch(
                ReservePoolCommand(other_actor, 1, "Foreign"), context=context("foreign")
            )
        ).value
        async with database.scope(org, readonly=False) as scope:
            rows = (await scope.links.list(org, 1, 10, pool.id)).items
            for row in (rows[0], rows[2]):
                await scope.links.subscribe(row.id, NormalizedEmail("one@example.com"))
        async with database.scope(foreign) as scope:
            outsider = (await scope.links.list(foreign, 1, 10, foreign_pool.id)).items[0]
        rename = RenamePoolCommand(actor, pool.id, "Renamed")
        first = await bus.dispatch(rename, context=context("rename"))
        await bus.dispatch(RenamePoolCommand(actor, pool.id, "Later"), context=context("later"))
        replay = await bus.dispatch(rename, context=context("rename"))
        assert first.value == replay.value and replay.replayed
        await bus.dispatch(
            UpdateLinkCommand(
                actor,
                rows[0].id,
                LinkPatch(frozenset({"destination_url"}), "https://example.com/ready"),
            ),
            context=context("activate"),
        )
        assert len(await _ready_emails(postgres_urls.worker, org, rows[0].id)) == 1
        with pytest.raises(LinkNotFoundError):
            await bus.dispatch(
                DeleteLinksCommand(actor, (rows[0].id, outsider.id)),
                context=context("foreign-selection"),
            )
        async with database.scope(org) as scope:
            assert (await scope.links.get_pool(org, pool.id)).size == 3
        with pytest.raises(LinkNotFoundError):
            await bus.dispatch(
                DeleteLinksCommand(actor, (rows[0].id,), other.id), context=context("wrong-pool")
            )
        deletion = DeleteLinksCommand(actor, (rows[0].id, rows[1].id), pool.id)
        await bus.dispatch(deletion, context=context("selection"))
        assert (await bus.dispatch(deletion, context=context("selection"))).replayed
        assert not await _ready_emails(postgres_urls.worker, org, rows[0].id)
        async with database.scope(org) as scope:
            assert (await scope.links.get_pool(org, pool.id)).size == 1
        delete_pool = DeletePoolCommand(actor, pool.id)
        await bus.dispatch(delete_pool, context=context("delete-pool"))
        assert (await bus.dispatch(delete_pool, context=context("delete-pool"))).replayed
        async with database.scope(org) as scope:
            with pytest.raises(LinkNotFoundError):
                await scope.links.get_pool(org, pool.id)
            assert (await scope.links.get_pool(org, other.id)).size == 1
            for row in rows:
                with pytest.raises(LinkNotFoundError):
                    await scope.links.public(row.short_code)
        from psycopg import AsyncConnection

        async with await AsyncConnection.connect(postgres_urls.owner) as connection:
            assert (
                await (
                    await connection.execute(
                        "SELECT count(*) FROM links.subscriptions WHERE organization_id=%s",
                        (org.uuid,),
                    )
                ).fetchone()
            )[0] == 0
    finally:
        await database.close()
        await _cleanup(postgres_urls.owner, (org, foreign))
