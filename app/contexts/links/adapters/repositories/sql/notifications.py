"""Worker-only PostgreSQL queue adapter. SMTP work is claimed with SKIP LOCKED."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from shared_observability.telemetry import TelemetryService
from shared_persistence import PostgresConnectionContext

from app.contexts.links.application.dto.notification import EmailJobDto
from app.contexts.links.application.telemetry import DEAD, OLDEST, PENDING


@dataclass
class PostgresDeliveryLease:
    connection: Any
    job: EmailJobDto | None

    async def complete(self) -> None:
        if self.job is not None:
            await self.connection.execute(
                "UPDATE platform.activation_emails SET sent_at=now(), "
                "attempts=attempts+1 WHERE id=%s",
                (self.job.id,),
            )

    async def fail(self) -> None:
        if self.job is not None:
            await self.connection.execute(
                "UPDATE platform.activation_emails SET attempts=attempts+1, "
                "next_attempt_at=now() + "
                "make_interval(secs => LEAST(3600, 30 * power(2, attempts)::int)) WHERE id=%s",
                (self.job.id,),
            )


class PostgresDeliveryQueue:
    def __init__(self, url: str) -> None:
        self._url = url

    @asynccontextmanager
    async def claim(self) -> AsyncIterator[PostgresDeliveryLease]:
        async with PostgresConnectionContext.open(self._url) as connection:
            async with connection.transaction():
                cursor = await connection.execute("""SELECT j.id,s.email,l.short_code,j.attempts,
                    j.traceparent,j.tracestate
                    FROM platform.activation_emails j
                    JOIN links.subscriptions s ON s.id=j.subscription_id
                    JOIN links.links l ON l.id=j.link_id
                    WHERE j.sent_at IS NULL AND j.attempts < 5 AND j.next_attempt_at <= now()
                    AND l.is_active AND l.destination_url IS NOT NULL
                    ORDER BY j.next_attempt_at,j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1""")
                row = await cursor.fetchone()
                job = EmailJobDto(*row) if row else None
                yield PostgresDeliveryLease(connection, job)

    async def sample(self, telemetry: TelemetryService) -> None:
        """Worker-only aggregate signals; no tenant or recipient dimensions."""
        async with PostgresConnectionContext.open(self._url) as connection:
            async with connection.transaction():
                await connection.execute("SET TRANSACTION READ ONLY")
                row = await (
                    await connection.execute("""SELECT
                    count(*) FILTER (WHERE j.attempts<5),
                    count(*) FILTER (WHERE j.attempts>=5),
                    coalesce(extract(epoch FROM now()-min(j.created_at)
                        FILTER (WHERE j.attempts<5 AND j.next_attempt_at<=now())),0)
                    FROM platform.activation_emails j JOIN links.links l ON l.id=j.link_id
                    WHERE j.sent_at IS NULL AND l.is_active AND l.destination_url IS NOT NULL
                """)
                ).fetchone()
        for definition, value in zip((PENDING, DEAD, OLDEST), row, strict=True):
            telemetry.metrics.emit(definition, value=float(value))

    async def cleanup(self) -> None:
        async with PostgresConnectionContext.open(self._url) as connection:
            async with connection.transaction():
                await connection.execute("""DELETE FROM links.subscriptions s
                    WHERE (s.created_at < now()-interval '365 days' AND NOT EXISTS (
                        SELECT 1 FROM platform.activation_emails j
                        JOIN links.links l ON l.id=j.link_id
                        WHERE j.subscription_id=s.id AND j.sent_at IS NULL AND j.attempts < 5
                        AND l.is_active AND l.destination_url IS NOT NULL))
                    OR EXISTS (SELECT 1 FROM platform.activation_emails j
                        WHERE j.subscription_id=s.id AND (
                            j.sent_at < now()-interval '30 days'
                            OR (j.attempts >= 5 AND j.created_at < now()-interval '30 days')))
                """)
