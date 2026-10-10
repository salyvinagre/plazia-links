"""Private workload capabilities and retry boundaries on the Flyway schema."""

from dataclasses import replace

import pytest
from psycopg import AsyncConnection
from shared_identity import OrganizationId
from shared_kernel import ActorContext, OperationContext, RequestContext

from app.contexts.access.domain.principal import Principal
from app.contexts.links.contracts import CreateLinkCommand, ReservePoolCommand, UpdateLinkCommand
from app.contexts.links.domain.link import (
    Entropy,
    IdempotencyConflictError,
    InvalidLinkError,
    LinkDraft,
    LinkNotFoundError,
    LinkPatch,
    Visibility,
)
from app.platform.composition import Container
from app.platform.database import PostgresDatabase, PostgresUowFactory
from tests.integration.test_postgres_links import _bind_organization, _cleanup
from tests.integration.test_postgres_links import postgres_urls as postgres_urls
from tests.support import FixtureAuthority


@pytest.mark.slow
async def test_private_workload_scope_activation_replay_and_expiry(postgres_urls):
    org = OrganizationId.new()
    issuer = "https://identity.example.test"
    actor = Principal(
        issuer,
        "printer",
        "printer-client",
        org,
        frozenset({"links:create", "links:read", "links:update"}),
        9999999999,
        "jwt",
    )
    database = PostgresDatabase(postgres_urls.app)
    context = RequestContext(
        ActorContext("printer", "machine"), OperationContext("request", idempotency_key="reserve")
    )
    try:
        await _bind_organization(postgres_urls.owner, issuer, org)
        async with await AsyncConnection.connect(postgres_urls.owner) as owner:
            await owner.execute(
                "UPDATE access.organizations SET workloads=%s "
                "WHERE issuer=%s AND organization_id=%s",
                ([actor.client_id, "second-client"], issuer, org.uuid),
            )
        bus, _ = Container.buses(database, PostgresUowFactory(database), FixtureAuthority())
        command = ReservePoolCommand(actor, 2)
        pool = (await bus.dispatch(command, context=context)).value
        assert pool.entropy is Entropy.high and pool.visibility is Visibility.workload_private
        assert (await bus.dispatch(command, context=context)).replayed
        second = replace(actor, client_id="second-client")
        other = (await bus.dispatch(ReservePoolCommand(second, 2), context=context)).value
        assert other.id != pool.id
        assert (await bus.dispatch(ReservePoolCommand(second, 2), context=context)).replayed
        async with database.scope(org, actor=actor) as scope:
            links = (await scope.links.list(org, 1, 10, pool.id)).items
            assert len(links) == 2 and all(len(row.short_code) == 32 for row in links)
        for outsider in (
            replace(actor, client_id="ordinary"),
            replace(actor, issuer=issuer + "/other"),
        ):
            async with database.scope(org, actor=outsider) as scope:
                assert (await scope.links.list(org, 1, 10)).total == 0
                assert (await scope.links.pools(org, 1, 10)).total == 0
                with pytest.raises(LinkNotFoundError):
                    await scope.links.get(org, links[0].id)
                stats = (await scope.links.statistics(org, (org,)))[org]
                assert stats.redirects == stats.waiting_views == 0
        for entropy, visibility in (
            (Entropy.low, None),
            (Entropy.medium, None),
            (None, Visibility.organization),
        ):
            with pytest.raises(InvalidLinkError):
                await bus.dispatch(
                    ReservePoolCommand(actor, 1, entropy=entropy, visibility=visibility),
                    context=RequestContext(
                        ActorContext("printer", "machine"),
                        OperationContext("request", idempotency_key=f"{entropy}-{visibility}"),
                    ),
                )
        activation = RequestContext(
            ActorContext("printer", "machine"),
            OperationContext("request", idempotency_key="activate"),
        )
        result = await bus.dispatch(
            UpdateLinkCommand(
                actor,
                links[0].id,
                LinkPatch(
                    frozenset({"destination_url"}), "https://portal.example/tickets/r/" + "a" * 32
                ),
            ),
            context=activation,
        )
        assert result.value.entropy is Entropy.high
        async with database.scope(None) as scope:
            assert (
                await scope.links.public(links[0].short_code)
            ).destination_url == result.value.destination_url
        async with await AsyncConnection.connect(postgres_urls.owner) as owner:
            await owner.execute(
                "UPDATE platform.command_receipts "
                "SET expires_at=clock_timestamp()-interval '1 second' WHERE organization_id=%s",
                (org.uuid,),
            )
        with pytest.raises(IdempotencyConflictError):
            await bus.dispatch(command, context=context)
    finally:
        await database.close()
        await _cleanup(postgres_urls.owner, (org,))


@pytest.mark.slow
async def test_organization_pool_is_shared_across_registered_clients(postgres_urls):
    org = OrganizationId.new()
    issuer = "https://identity.example.test"
    actor = Principal(
        issuer,
        "manager",
        "first-client",
        org,
        frozenset({"links:create", "links:read"}),
        9999999999,
        "jwt",
    )
    database = PostgresDatabase(postgres_urls.app)
    context = RequestContext(
        ActorContext("manager", "human"), OperationContext("request", idempotency_key="shared")
    )
    try:
        await _bind_organization(postgres_urls.owner, issuer, org)
        bus, _ = Container.buses(database, PostgresUowFactory(database), FixtureAuthority())
        pool = (await bus.dispatch(ReservePoolCommand(actor, 1), context=context)).value
        second = replace(actor, client_id="second-client")
        link = (
            await bus.dispatch(
                CreateLinkCommand(
                    second, LinkDraft("https://portal.example/item", pool_id=pool.id)
                ),
                context=context,
            )
        ).value
        assert link.pool_id == pool.id and link.visibility is Visibility.organization
        async with database.scope(org, actor=actor) as scope:
            assert (await scope.links.get(org, link.id)).id == link.id
    finally:
        await database.close()
        await _cleanup(postgres_urls.owner, (org,))
