"""Worker recovery and competing claims against the actual Flyway-owned schema."""

import asyncio

import pytest
from shared_identity import OrganizationId
from shared_kernel.contacts import NormalizedEmail
from shared_persistence import PostgresConnectionContext

from app.contexts.links.adapters.repositories.sql.notifications import PostgresDeliveryQueue
from app.contexts.links.domain.link import LinkPatch, PublicCode
from app.platform.database import PostgresDatabase
from app.platform.persistence.schema import SchemaAuthority, SchemaError
from tests.integration.test_postgres_links import _bind_organization, _cleanup
from tests.integration.test_postgres_links import postgres_urls as postgres_urls


@pytest.mark.slow
async def test_claims_recovery_bounded_retries_and_runtime_roles(postgres_urls):
    urls = postgres_urls
    assert SchemaAuthority(urls.app).check(runtime="app").revision == "1"
    assert SchemaAuthority(urls.worker).check(runtime="worker").revision == "1"
    with pytest.raises(SchemaError, match="dedicated role"):
        SchemaAuthority(urls.owner).check(runtime="app")
    org = OrganizationId.new()
    database = PostgresDatabase(urls.app)
    try:
        await _bind_organization(urls.owner, "https://identity.example.test", org)
        async with database.scope(org, readonly=False) as scope:
            pool = await scope.links.reserve(org, "Worker recovery", (PublicCode.generate(),))
            link = (await scope.links.list(org, 1, 20, pool.id)).items[0]
            for email in ("first@example.test", "second@example.test"):
                await scope.links.subscribe(link.id, NormalizedEmail(email))
            await scope.links.update(
                org, link.id, LinkPatch(frozenset({"destination_url"}), "https://example.com/ready")
            )
            await scope.links.ready_subscriptions(org, link.id)
        queue = PostgresDeliveryQueue(urls.worker)
        async with queue.claim() as first:
            assert first.job is not None
            async with queue.claim() as second:
                assert second.job is not None and second.job.id != first.job.id
                retry_id = second.job.id
                await second.fail()
            await first.complete()
        async with queue.claim() as empty:
            assert empty.job is None
        async with PostgresConnectionContext.open(urls.owner) as connection:
            row = await (
                await connection.execute(
                    "SELECT attempts,next_attempt_at > now() "
                    "FROM platform.activation_emails WHERE id=%s",
                    (retry_id,),
                )
            ).fetchone()
            assert row == (1, True)
            await connection.execute(
                "UPDATE platform.activation_emails SET next_attempt_at=now() WHERE id=%s",
                (retry_id,),
            )
            await connection.commit()
        with pytest.raises(asyncio.CancelledError):
            async with queue.claim() as cancelled:
                assert cancelled.job.id == retry_id and cancelled.job.attempts == 1
                await cancelled.complete()
                raise asyncio.CancelledError
        async with queue.claim() as recovered:
            assert recovered.job.id == retry_id and recovered.job.attempts == 1
            await recovered.fail()
        async with PostgresConnectionContext.open(urls.owner) as connection:
            await connection.execute(
                "UPDATE platform.activation_emails SET attempts=4,next_attempt_at=now() "
                "WHERE id=%s",
                (retry_id,),
            )
            await connection.commit()
        async with queue.claim() as last:
            assert last.job.attempts == 4
            await last.fail()
        async with queue.claim() as dead:
            assert dead.job is None
        async with database.scope(org, readonly=False) as scope:
            await scope.links.delete(org, link.id)
        async with PostgresConnectionContext.open(urls.worker) as connection:
            count = await (
                await connection.execute(
                    "SELECT count(*) FROM platform.activation_emails WHERE id=%s", (retry_id,)
                )
            ).fetchone()
            assert count == (0,)
    finally:
        await database.close()
        await _cleanup(urls.owner, (org,))
