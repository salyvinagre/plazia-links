"""Native PostgreSQL proof of pixel isolation, capture, revocation and replay."""

import asyncio

import pytest
from psycopg import AsyncConnection
from psycopg.errors import InsufficientPrivilege, ReadOnlySqlTransaction
from shared_identity import OrganizationId

from app.contexts.links.contracts import (
    PixelCode,
    PixelConflictError,
    PixelDraft,
    PixelNotFoundError,
)
from app.platform.database import PostgresDatabase
from tests.integration.test_postgres_links import postgres_urls as postgres_urls


@pytest.mark.slow
async def test_pixels_are_atomic_scoped_readonly_and_revocable(postgres_urls):
    database = PostgresDatabase(postgres_urls.app)
    organization, other = OrganizationId.new(), OrganizationId.new()
    try:
        async with database.scope(organization, readonly=False) as scope:
            pixel = await scope.pixels.create(
                organization, PixelDraft("delivery-1842"), PixelCode.generate()
            )
            # A generated-code collision must roll back its savepoint, not poison the UoW.
            with pytest.raises(PixelConflictError):
                await scope.pixels.create(organization, PixelDraft(), pixel.code)
            recovered = await scope.pixels.create(organization, PixelDraft(), PixelCode.generate())
            await scope.pixels.delete(organization, recovered.id)
        async with database.scope(organization) as scope:
            read = await scope.pixels.get(organization, pixel.id)
            assert read.statistics.requests == 0 and read.statistics.first_requested_at is None
        async with database.scope() as scope:
            assert await scope.pixels.public(pixel.code) == pixel.id
            with pytest.raises(PixelNotFoundError):
                await scope.pixels.public(PixelCode.generate())
        with pytest.raises(ReadOnlySqlTransaction):
            async with database.scope() as scope:
                await scope.pixels.record(pixel.id, pixel.code)

        async def record():
            async with database.scope(readonly=False) as scope:
                await scope.pixels.record(pixel.id, pixel.code)

        await asyncio.gather(*(record() for _ in range(24)))
        with pytest.raises(RuntimeError):
            async with database.scope(readonly=False) as scope:
                await scope.pixels.record(pixel.id, pixel.code)
                raise RuntimeError("Rollback")
        async with database.scope(readonly=False) as scope:
            await scope.pixels.record(pixel.id, PixelCode.generate())
        async with database.scope(organization) as scope:
            read = await scope.pixels.get(organization, pixel.id)
            stats = read.statistics
            assert stats.requests == 24
            assert (
                pixel.created_at
                <= stats.first_requested_at
                <= stats.last_requested_at
                <= stats.as_of
            )
            page = await scope.pixels.list(organization, 1, 20)
            assert page.total == 1 and page.items[0].id == pixel.id
        async with database.scope(other) as scope:
            assert (await scope.pixels.list(other, 1, 20)).total == 0
            with pytest.raises(PixelNotFoundError):
                await scope.pixels.get(other, pixel.id)
        async with database.scope(other, readonly=False) as scope:
            with pytest.raises(PixelNotFoundError):
                await scope.pixels.delete(other, pixel.id)
        for url, statement in (
            (postgres_urls.app, "UPDATE links.pixels SET requests=9000"),
            (
                postgres_urls.app,
                "INSERT INTO links.pixels (organization_id,code,requests) VALUES (uuidv7(),'"
                + "a" * 32
                + "',9000)",
            ),
            (postgres_urls.worker, "SELECT * FROM links.pixels"),
            (postgres_urls.worker, "SELECT links.resolve_public_pixel('" + pixel.code + "')"),
            (
                postgres_urls.worker,
                "SELECT links.record_pixel_request('"
                + str(pixel.id.uuid)
                + "','"
                + pixel.code
                + "')",
            ),
        ):
            with pytest.raises(InsufficientPrivilege):
                async with await AsyncConnection.connect(url) as connection:
                    await connection.execute(statement)
        async with database.scope(organization, readonly=False) as scope:
            await scope.pixels.delete(organization, pixel.id)
        async with database.scope() as scope:
            with pytest.raises(PixelNotFoundError):
                await scope.pixels.public(pixel.code)
        # A raced capture after deletion cannot recreate the resource or its aggregate.
        await record()
        async with database.scope(organization) as scope:
            assert (await scope.pixels.list(organization, 1, 20)).total == 0
    finally:
        await database.close()
