"""PostgreSQL adapter for Identity organization bindings."""

from shared_identity.canonical_ids import OrganizationId
from shared_persistence import AsyncPostgresRuntimeConnection

from app.contexts.access.application.dto.organization import OrganizationDto
from app.contexts.access.application.ports.organizations import OrganizationRepository


class PostgresOrganizationRepository(OrganizationRepository):
    def __init__(self, connection: AsyncPostgresRuntimeConnection) -> None:
        self._connection = connection

    async def find(self, issuer: str, organization_id: OrganizationId) -> OrganizationDto | None:
        cursor = await self._connection.execute(
            "SELECT organization_id, name, is_active "
            "FROM access.organizations WHERE issuer = %s AND organization_id = %s",
            (issuer, organization_id.uuid),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return OrganizationDto(
            id=OrganizationId(uuid=row[0]),
            name=row[1],
            is_active=row[2],
        )

    async def bind(self, issuer: str, organization_id: OrganizationId, name: str) -> None:
        await self._connection.execute(
            """
            INSERT INTO access.organizations (issuer, organization_id, name, is_active)
            VALUES (%s, %s, %s, true)
            ON CONFLICT (issuer, organization_id) DO UPDATE
            SET name = EXCLUDED.name, is_active = true, updated_at = clock_timestamp()
            """,
            (issuer, organization_id.uuid, name),
        )

    async def disable(self, issuer: str, organization_id: OrganizationId) -> None:
        await self._connection.execute(
            """
            UPDATE access.organizations
            SET is_active = false, updated_at = clock_timestamp()
            WHERE issuer = %s AND organization_id = %s
            """,
            (issuer, organization_id.uuid),
        )


__all__ = ["PostgresOrganizationRepository"]
