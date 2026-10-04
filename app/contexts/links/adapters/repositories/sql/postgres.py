"""PostgreSQL repositories for organization-owned links and public subscriptions."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any, cast

from psycopg import Error
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from shared_identity.canonical_ids import OrganizationId
from shared_kernel.contacts import NormalizedEmail
from shared_messaging.invocation import Invocation
from shared_persistence import AsyncPostgresRuntimeConnection

from app.contexts.access.contracts import Principal
from app.contexts.links.application.dto.links import (
    CommandResultDto,
    LinkDto,
    PageDto,
    PoolDto,
    PublicLinkDto,
)
from app.contexts.links.application.dto.statistics import StatisticsDto, VisitOutcome
from app.contexts.links.application.errors.statistics import StatisticsUnavailableError
from app.contexts.links.domain.link import (
    IdempotencyConflictError,
    LinkConflictError,
    LinkDisabledError,
    LinkDraft,
    LinkNotFoundError,
    LinkPatch,
    PublicCode,
)
from app.kernel.ids import LinkId, PoolId

_CODE_CONSTRAINT = "uq_links_short_code"
_LINK_ID_CONSTRAINT = "links_pkey"
_POOL_ID_CONSTRAINT = "pools_pkey"


class PostgresLinkRepository:
    def __init__(self, connection: AsyncPostgresRuntimeConnection) -> None:
        self._connection = connection

    async def record_visit(self, link_id: LinkId, code: str, outcome: VisitOutcome) -> None:
        await self._connection.execute(
            "SELECT links.record_visit(%s,%s,%s)", (link_id.uuid, code, outcome)
        )

    async def statistics(
        self,
        organization_id: OrganizationId,
        ids: tuple[OrganizationId | LinkId | PoolId, ...],
    ) -> dict[OrganizationId | LinkId | PoolId, StatisticsDto]:
        if not ids:
            return {}
        kinds = [
            "link"
            if isinstance(id, LinkId)
            else "pool"
            if isinstance(id, PoolId)
            else "organization"
            for id in ids
        ]
        try:
            cursor = await self._connection.execute(
                """WITH targets AS (
                SELECT * FROM unnest(%s::uuid[], %s::text[]) WITH ORDINALITY AS t(id,kind,position)
            ), selected AS (
                SELECT t.position,l.organization_id,l.id FROM targets t
                JOIN links.links l ON l.organization_id = %s AND (
                    (t.kind='link' AND l.id=t.id) OR
                    (t.kind='pool' AND l.pool_id=t.id) OR
                    (t.kind='organization' AND l.organization_id=t.id))
            ), subscribers AS (
                SELECT link_id, count(*) AS total FROM links.subscriptions
                WHERE organization_id=%s AND link_id IN (SELECT id FROM selected)
                GROUP BY link_id
            )
            SELECT t.position, coalesce(sum(s.redirects),0)::bigint,
                   coalesce(sum(s.waiting_views),0)::bigint,
                   coalesce(sum(u.total),0)::bigint, max(s.last_visited_at),
                   c.started_at, clock_timestamp()
            FROM targets t CROSS JOIN links.statistics_coverage c
            LEFT JOIN selected l ON l.position=t.position
            LEFT JOIN links.statistics s ON s.organization_id=l.organization_id AND s.link_id=l.id
            LEFT JOIN subscribers u ON u.link_id=l.id
            GROUP BY t.position,c.started_at""",
                ([id.uuid for id in ids], kinds, organization_id.uuid, organization_id.uuid),
            )
            result = {ids[row[0] - 1]: StatisticsDto(*row[1:]) for row in await cursor.fetchall()}
        except (Error, ValueError) as error:
            raise StatisticsUnavailableError from error
        if len(result) != len(ids):
            raise StatisticsUnavailableError
        return result

    async def replay(
        self, actor: Principal, action: str, key: str, fingerprint: str
    ) -> CommandResultDto | None:
        identity = (actor.organization_id.uuid, actor.issuer, actor.subject, action, key)
        await self._connection.execute(
            """INSERT INTO platform.command_receipts
            (organization_id,issuer,subject,action,key,fingerprint)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (*identity, fingerprint),
        )
        row = await (
            await self._connection.execute(
                """SELECT fingerprint,result
            FROM platform.command_receipts WHERE organization_id=%s AND issuer=%s
            AND subject=%s AND action=%s AND key=%s FOR UPDATE""",
                identity,
            )
        ).fetchone()
        if row[0] != fingerprint:
            raise IdempotencyConflictError
        if row[1] is None:
            return None
        if row[1]["value"] is None:
            return CommandResultDto(None, True)
        values = dict(row[1]["value"])
        values["created_at"] = datetime.fromisoformat(values["created_at"])
        if action in {"ReservePoolCommand", "RenamePoolCommand"}:
            values["id"] = PoolId(values["id"])
            return CommandResultDto(PoolDto(**values), True)
        values["id"] = LinkId(values["id"])
        values["pool_id"] = PoolId(values["pool_id"]) if values["pool_id"] else None
        values["updated_at"] = datetime.fromisoformat(values["updated_at"])
        return CommandResultDto(LinkDto(**values), True)

    async def remember(
        self, actor: Principal, action: str, key: str, result: LinkDto | PoolDto | None
    ) -> None:
        snapshot = {
            "value": json.loads(json.dumps(asdict(result), default=str)) if result else None
        }
        await self._connection.execute(
            """UPDATE platform.command_receipts SET result=%s
            WHERE organization_id=%s AND issuer=%s AND subject=%s AND action=%s AND key=%s""",
            (Jsonb(snapshot), actor.organization_id.uuid, actor.issuer, actor.subject, action, key),
        )

    async def list(
        self,
        organization_id: OrganizationId,
        page: int,
        page_size: int,
        pool_id: PoolId | None = None,
    ) -> PageDto[LinkDto]:
        where = "organization_id = %s"
        parameters: list[object] = [organization_id.uuid]
        if pool_id is not None:
            where += " AND pool_id = %s"
            parameters.append(pool_id.uuid)
        count_cursor = await self._connection.execute(
            f"SELECT count(*) FROM links.links WHERE {where}",
            tuple(parameters),
        )
        total = int((await count_cursor.fetchone())[0])
        cursor = await self._connection.execute(
            f"""
            SELECT id, organization_id, pool_id, short_code, destination_url,
                   title, notes, is_active, created_at, updated_at
            FROM links.links
            WHERE {where}
            ORDER BY created_at DESC, id DESC
            LIMIT %s OFFSET %s
            """,
            (*parameters, page_size, (page - 1) * page_size),
        )
        rows = await cursor.fetchall()
        return PageDto(
            items=tuple(self._link(row) for row in rows),
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get(
        self,
        organization_id: OrganizationId,
        link_id: LinkId,
        *,
        lock: bool = False,
    ) -> LinkDto:
        suffix = " FOR UPDATE" if lock else ""
        cursor = await self._connection.execute(
            f"""
            SELECT id, organization_id, pool_id, short_code, destination_url,
                   title, notes, is_active, created_at, updated_at
            FROM links.links
            WHERE organization_id = %s AND id = %s{suffix}
            """,
            (organization_id.uuid, link_id.uuid),
        )
        row = await cursor.fetchone()
        if row is None:
            raise LinkNotFoundError(str(link_id))
        return self._link(row)

    async def create(self, organization_id: OrganizationId, draft: LinkDraft) -> LinkDto:
        short_code = draft.short_code or PublicCode.generate()
        try:
            async with self._connection.transaction():
                cursor = await self._connection.execute(
                    """
                    INSERT INTO links.links
                        (organization_id, pool_id, short_code, destination_url,
                         title, notes, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, true)
                    RETURNING id, organization_id, pool_id, short_code, destination_url,
                              title, notes, is_active, created_at, updated_at
                    """,
                    (
                        organization_id.uuid,
                        draft.pool_id.uuid if draft.pool_id is not None else None,
                        short_code,
                        draft.destination_url,
                        draft.title,
                        draft.notes,
                    ),
                )
                row = await cursor.fetchone()
            return self._link(row)
        except UniqueViolation as error:
            constraint = self._constraint(error)
            if constraint == _CODE_CONSTRAINT:
                raise LinkConflictError(short_code) from error
            if constraint == _LINK_ID_CONSTRAINT:
                raise LinkConflictError("could not allocate a unique link identifier") from error
            raise

    async def update(
        self,
        organization_id: OrganizationId,
        link_id: LinkId,
        patch: LinkPatch,
    ) -> LinkDto:
        fields = patch.fields
        cursor = await self._connection.execute(
            """
            UPDATE links.links
            SET destination_url = CASE WHEN %s THEN %s ELSE destination_url END,
                title = CASE WHEN %s THEN %s ELSE title END,
                notes = CASE WHEN %s THEN %s ELSE notes END,
                is_active = CASE WHEN %s THEN %s ELSE is_active END,
                updated_at = clock_timestamp()
            WHERE organization_id = %s AND id = %s
            RETURNING id, organization_id, pool_id, short_code, destination_url,
                      title, notes, is_active, created_at, updated_at
            """,
            (
                "destination_url" in fields,
                patch.destination_url,
                "title" in fields,
                patch.title,
                "notes" in fields,
                patch.notes,
                "is_active" in fields,
                patch.is_active,
                organization_id.uuid,
                link_id.uuid,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            raise LinkNotFoundError(str(link_id))
        return self._link(row)

    async def delete(self, organization_id: OrganizationId, link_id: LinkId) -> None:
        await self.delete_many(organization_id, (link_id,))

    async def delete_many(
        self,
        organization_id: OrganizationId,
        ids: tuple[LinkId, ...],
        pool_id: PoolId | None = None,
        *,
        all: bool = False,
    ) -> tuple[LinkId, ...]:
        if all and pool_id is not None:
            await self.get_pool(organization_id, pool_id)
        parameters: tuple[object, ...] = (organization_id.uuid,)
        where = "organization_id = %s"
        if not all:
            where += " AND id = ANY(%s)"
            parameters += ([id.uuid for id in ids],)
        if pool_id is not None:
            where += " AND pool_id = %s"
            parameters += (pool_id.uuid,)
        # Lock in a stable order before deleting overlapping selections.
        cursor = await self._connection.execute(
            f"SELECT id FROM links.links WHERE {where} ORDER BY id FOR UPDATE", parameters
        )
        rows = await cursor.fetchall()
        if not all and len(rows) != len(ids):
            raise LinkNotFoundError("selection")
        # Delete exactly the locked set; a later insert must not escape the audit.
        await self._connection.execute(
            "DELETE FROM links.links WHERE organization_id = %s AND id = ANY(%s)",
            (organization_id.uuid, [row[0] for row in rows]),
        )
        return tuple(LinkId(uuid=row[0]) for row in rows)

    async def reserve(
        self,
        organization_id: OrganizationId,
        name: str | None,
        codes: tuple[str, ...],
    ) -> PoolDto:
        for _ in range(5):
            try:
                async with self._connection.transaction():
                    cursor = await self._connection.execute(
                        """
                        INSERT INTO links.pools (organization_id, name)
                        VALUES (%s, %s)
                        RETURNING id, name, created_at
                        """,
                        (organization_id.uuid, name),
                    )
                    pool_row = await cursor.fetchone()
                    for short_code in codes:
                        await self._connection.execute(
                            """
                            INSERT INTO links.links
                                (organization_id, pool_id, short_code, destination_url, is_active)
                            VALUES (%s, %s, %s, NULL, true)
                            """,
                            (organization_id.uuid, pool_row[0], short_code),
                        )
                return PoolDto(
                    id=PoolId(uuid=pool_row[0]),
                    name=pool_row[1],
                    size=len(codes),
                    created_at=pool_row[2],
                )
            except UniqueViolation as error:
                constraint = self._constraint(error)
                if constraint == _CODE_CONSTRAINT:
                    raise LinkConflictError("a public code is already allocated") from error
                if constraint in {_POOL_ID_CONSTRAINT, _LINK_ID_CONSTRAINT}:
                    continue
                raise
        raise LinkConflictError("could not allocate a unique database-generated identifier")

    async def rename_pool(
        self, organization_id: OrganizationId, pool_id: PoolId, name: str | None
    ) -> PoolDto:
        cursor = await self._connection.execute(
            "UPDATE links.pools SET name = %s WHERE organization_id = %s AND id = %s RETURNING id",
            (name, organization_id.uuid, pool_id.uuid),
        )
        if await cursor.fetchone() is None:
            raise LinkNotFoundError(str(pool_id))
        return await self.get_pool(organization_id, pool_id)

    async def delete_pool(self, organization_id: OrganizationId, pool_id: PoolId) -> None:
        cursor = await self._connection.execute(
            "DELETE FROM links.pools WHERE organization_id = %s AND id = %s RETURNING id",
            (organization_id.uuid, pool_id.uuid),
        )
        if await cursor.fetchone() is None:
            raise LinkNotFoundError(str(pool_id))

    async def get_pool(self, organization_id: OrganizationId, pool_id: PoolId) -> PoolDto:
        cursor = await self._connection.execute(
            """
            SELECT p.id, p.name, p.created_at, count(l.id)
            FROM links.pools AS p
            LEFT JOIN links.links AS l
              ON l.organization_id = p.organization_id AND l.pool_id = p.id
            WHERE p.organization_id = %s AND p.id = %s
            GROUP BY p.id, p.name, p.created_at
            """,
            (organization_id.uuid, pool_id.uuid),
        )
        row = await cursor.fetchone()
        if row is None:
            raise LinkNotFoundError(str(pool_id))
        return PoolDto(
            id=PoolId(uuid=row[0]),
            name=row[1],
            created_at=row[2],
            size=int(row[3]),
        )

    async def pools(
        self,
        organization_id: OrganizationId,
        page: int,
        page_size: int,
    ) -> PageDto[PoolDto]:
        count_cursor = await self._connection.execute(
            "SELECT count(*) FROM links.pools WHERE organization_id = %s",
            (organization_id.uuid,),
        )
        total = int((await count_cursor.fetchone())[0])
        cursor = await self._connection.execute(
            """
            SELECT p.id, p.name, p.created_at, count(l.id)
            FROM links.pools AS p
            LEFT JOIN links.links AS l
              ON l.organization_id = p.organization_id AND l.pool_id = p.id
            WHERE p.organization_id = %s
            GROUP BY p.id, p.name, p.created_at
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT %s OFFSET %s
            """,
            (organization_id.uuid, page_size, (page - 1) * page_size),
        )
        rows = await cursor.fetchall()
        return PageDto(
            items=tuple(
                PoolDto(
                    id=PoolId(uuid=row[0]),
                    name=row[1],
                    created_at=row[2],
                    size=int(row[3]),
                )
                for row in rows
            ),
            total=total,
            page=page,
            page_size=page_size,
        )

    async def ready_subscriptions(
        self,
        organization_id: OrganizationId,
        link_id: LinkId,
        context: Invocation | None = None,
    ) -> None:
        from shared_observability.tracing import current_trace_headers

        carrier = current_trace_headers()
        operation = context.operation_context if context is not None else None
        await self._connection.execute(
            "SELECT links.ready_subscriptions(%s, %s, %s, %s)",
            (
                organization_id.uuid,
                link_id.uuid,
                carrier.get("traceparent") or (operation.traceparent if operation else None),
                carrier.get("tracestate") or (operation.tracestate if operation else None),
            ),
        )

    async def public(self, short_code: str, *, lock: bool = False) -> PublicLinkDto:
        cursor = await self._connection.execute(
            "SELECT id, short_code, destination_url, is_active "
            "FROM links.resolve_public_link(%s, %s)",
            (short_code, lock),
        )
        row = await cursor.fetchone()
        if row is None:
            raise LinkNotFoundError(short_code)
        return PublicLinkDto(
            id=LinkId(uuid=row[0]),
            short_code=row[1],
            destination_url=row[2],
            is_active=row[3],
        )

    async def subscribe(self, link_id: LinkId, email: NormalizedEmail) -> None:
        cursor = await self._connection.execute(
            "SELECT links.subscribe_reserved_link(%s, %s)",
            (link_id.uuid, str(email)),
        )
        state = (await cursor.fetchone())[0]
        if state == "disabled":
            raise LinkDisabledError(str(link_id))
        if state == "missing":
            raise LinkNotFoundError(str(link_id))

    async def audit(
        self,
        organization_id: OrganizationId,
        action: str,
        resource_ids: tuple[LinkId | PoolId, ...],
        context: Invocation,
    ) -> None:
        actor = context.actor_context
        operation = context.operation_context
        await self._connection.execute(
            """
            INSERT INTO platform.audit_events
                (organization_id, action, resource_type, resource_id, actor_id, actor_type,
                 principal_id, principal_type, request_id, correlation_id, source_channel,
                 traceparent, tracestate, idempotency_key)
            SELECT %s, %s, resource.type, resource.id, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            FROM unnest(%s::text[], %s::uuid[]) AS resource(type, id)
            """,
            (
                organization_id.uuid,
                action,
                actor.actor_id,
                actor.actor_type,
                actor.principal_id,
                actor.principal_type,
                operation.request_id,
                operation.correlation_id,
                operation.source_channel,
                operation.traceparent,
                operation.tracestate,
                operation.idempotency_key,
                ["link" if isinstance(id, LinkId) else "pool" for id in resource_ids],
                [id.uuid for id in resource_ids],
            ),
        )

    @staticmethod
    def _link(row: object) -> LinkDto:
        values = cast(tuple[Any, ...], row)
        return LinkDto(
            id=LinkId(uuid=values[0]),
            short_code=values[3],
            destination_url=values[4],
            title=values[5],
            notes=values[6],
            is_active=values[7],
            created_at=values[8],
            updated_at=values[9],
            pool_id=PoolId(uuid=values[2]) if values[2] is not None else None,
        )

    @staticmethod
    def _constraint(error: UniqueViolation) -> str | None:
        diagnostic = error.diag
        return diagnostic.constraint_name if diagnostic is not None else None


__all__ = ["PostgresLinkRepository"]
