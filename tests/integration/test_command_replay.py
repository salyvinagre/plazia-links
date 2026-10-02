"""Concurrent durable replay through the real shared command bus and PostgreSQL UoW."""

import asyncio

import pytest
from shared_identity import OrganizationId
from shared_kernel import ActorContext, OperationContext, RequestContext

from app.contexts.access.domain.principal import Principal
from app.contexts.links.contracts import ReservePoolCommand
from app.contexts.links.domain.link import IdempotencyConflictError
from app.platform.composition import build_buses
from app.platform.database import PostgresDatabase, PostgresUowFactory
from tests.integration.test_postgres_links import _bind_organization, _cleanup
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
