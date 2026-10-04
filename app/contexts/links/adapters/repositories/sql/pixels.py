"""Pixel definitions and atomic request aggregates share one tenant-owned row."""

from typing import Any

from psycopg.errors import UniqueViolation
from shared_identity import OrganizationId
from shared_persistence import AsyncPostgresRuntimeConnection

from app.contexts.links.application.dto.links import PageDto
from app.contexts.links.application.dto.pixels import PixelDto, PixelReadDto, PixelStatisticsDto
from app.contexts.links.domain.pixel import PixelConflictError, PixelDraft, PixelNotFoundError
from app.kernel.ids import PixelId


class PostgresPixelRepository:
    _COLUMNS = (
        "id, code, reference, created_at, requests, first_requested_at, "
        "last_requested_at, clock_timestamp()"
    )

    def __init__(self, connection: AsyncPostgresRuntimeConnection) -> None:
        self._connection = connection

    async def create(
        self, organization_id: OrganizationId, draft: PixelDraft, code: str
    ) -> PixelDto:
        try:
            async with self._connection.transaction():
                cursor = await self._connection.execute(
                    """INSERT INTO links.pixels (organization_id,code,reference)
                    VALUES (%s,%s,%s) RETURNING id,code,reference,created_at""",
                    (organization_id.uuid, code, draft.reference),
                )
                row = await cursor.fetchone()
            return PixelDto(PixelId(uuid=row[0]), *row[1:])
        except UniqueViolation as error:
            if error.diag.constraint_name not in {"pixels_pkey", "uq_pixels_code"}:
                raise
            raise PixelConflictError from error

    async def get(self, organization_id: OrganizationId, id: PixelId) -> PixelReadDto:
        cursor = await self._connection.execute(
            f"SELECT {self._COLUMNS} FROM links.pixels WHERE organization_id=%s AND id=%s",
            (organization_id.uuid, id.uuid),
        )
        row = await cursor.fetchone()
        if row is None:
            raise PixelNotFoundError
        return self._read(row)

    async def list(
        self, organization_id: OrganizationId, page: int, page_size: int
    ) -> PageDto[PixelReadDto]:
        cursor = await self._connection.execute(
            "SELECT count(*) FROM links.pixels WHERE organization_id=%s", (organization_id.uuid,)
        )
        total = (await cursor.fetchone())[0]
        cursor = await self._connection.execute(
            f"""SELECT {self._COLUMNS} FROM links.pixels WHERE organization_id=%s
            ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s""",
            (organization_id.uuid, page_size, (page - 1) * page_size),
        )
        return PageDto(
            tuple(self._read(row) for row in await cursor.fetchall()), total, page, page_size
        )

    async def delete(self, organization_id: OrganizationId, id: PixelId) -> None:
        cursor = await self._connection.execute(
            "DELETE FROM links.pixels WHERE organization_id=%s AND id=%s RETURNING id",
            (organization_id.uuid, id.uuid),
        )
        if await cursor.fetchone() is None:
            raise PixelNotFoundError

    async def public(self, code: str) -> PixelId:
        row = await (
            await self._connection.execute("SELECT links.resolve_public_pixel(%s)", (code,))
        ).fetchone()
        if row[0] is None:
            raise PixelNotFoundError
        return PixelId(uuid=row[0])

    async def record(self, id: PixelId, code: str) -> None:
        await self._connection.execute("SELECT links.record_pixel_request(%s,%s)", (id.uuid, code))

    @staticmethod
    def _read(row: tuple[Any, ...]) -> PixelReadDto:
        return PixelReadDto(
            id=PixelId(uuid=row[0]),
            code=row[1],
            reference=row[2],
            created_at=row[3],
            statistics=PixelStatisticsDto(*row[4:]),
        )
