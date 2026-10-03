"""PostgreSQL transaction scopes and command unit of work."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import cast

from shared_identity.canonical_ids import OrganizationId
from shared_messaging.unit_of_work import BaseCommandUnitOfWork
from shared_persistence import (
    PostgresConnectionContext,
    PostgresRuntimeDatabase,
    PostgresRuntimeHandle,
    PostgresSessionConfiguration,
    configure_postgres_transaction,
)

from app.contexts.access.adapters.repositories.sql.postgres import (
    PostgresOrganizationRepository,
)
from app.contexts.access.application.policies.organization import OrganizationAccess
from app.contexts.access.application.ports.organizations import OrganizationRepository
from app.contexts.access.contracts import OrganizationAccessPort
from app.contexts.links.adapters.repositories.sql.postgres import PostgresLinkRepository
from app.contexts.links.application.ports.repository import LinkRepository

_POSTGRES_CONFIGURATION = PostgresSessionConfiguration(
    search_path=("links", "access", "platform", "public"),
    organization_id_setting="plazia.organization_id",
)


@dataclass(slots=True)
class Scope:
    """Repositories and policy bound to one PostgreSQL transaction."""

    links: LinkRepository
    organizations: OrganizationRepository
    access: OrganizationAccessPort


class PostgresDatabase:
    """Own a pooled PostgreSQL runtime or open one connection per scope."""

    def __init__(self, url: str, *, pooled: bool = True) -> None:
        if not url.strip().startswith(("postgresql://", "postgres://")):
            raise ValueError("PostgreSQL URL is required")
        self._url = url.strip()
        self._runtime = (
            PostgresRuntimeDatabase.from_url(
                url,
                min_size=1,
                max_size=8,
                configuration=_POSTGRES_CONFIGURATION,
            )
            if pooled
            else None
        )

    @asynccontextmanager
    async def scope(
        self,
        organization_id: OrganizationId | None = None,
        *,
        readonly: bool = True,
    ) -> AsyncIterator[Scope]:
        """Yield repositories after setting transaction-local tenant and access mode."""

        source = (
            cast(PostgresRuntimeHandle, self._runtime) if self._runtime is not None else self._url
        )
        async with PostgresConnectionContext.open(
            source,
            organization_id=str(organization_id) if organization_id is not None else None,
            configuration=_POSTGRES_CONFIGURATION,
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SET TRANSACTION READ ONLY" if readonly else "SET TRANSACTION READ WRITE"
                )
                await configure_postgres_transaction(
                    connection,
                    organization_id=str(organization_id) if organization_id is not None else None,
                    configuration=_POSTGRES_CONFIGURATION,
                )
                organizations = PostgresOrganizationRepository(connection)
                yield Scope(
                    links=PostgresLinkRepository(connection),
                    organizations=organizations,
                    access=OrganizationAccess(organizations),
                )

    async def close(self) -> None:
        """Close a pooled runtime; per-scope connections need no retained cleanup."""

        if self._runtime is not None:
            await self._runtime.close()


class PostgresUowFactory:
    """Create one writable transaction for each command-bus dispatch."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def start(self, envelope: object) -> BaseCommandUnitOfWork:
        command = getattr(envelope, "command", None)
        actor = getattr(command, "actor", None)
        organization_id = getattr(actor, "organization_id", None)
        if organization_id is not None and not isinstance(organization_id, OrganizationId):
            raise TypeError("command actor organization_id must be a shared OrganizationId")
        return _PostgresCommandUnitOfWork(self._database, organization_id)


class _PostgresCommandUnitOfWork(BaseCommandUnitOfWork):
    def __init__(
        self,
        database: PostgresDatabase,
        organization_id: OrganizationId | None,
    ) -> None:
        super().__init__(scope=None)
        self._database = database
        self._organization_id = organization_id
        self._scope_context: AbstractAsyncContextManager[Scope] | None = None

    async def _enter(self) -> None:
        if self._scope_context is not None:
            raise RuntimeError("PostgreSQL unit of work has already been entered")
        self._scope_context = self._database.scope(self._organization_id, readonly=False)
        self._scope = await self._scope_context.__aenter__()

    async def _commit(self) -> None:
        if self._scope_context is None:
            raise RuntimeError("PostgreSQL unit of work is not open")
        context, self._scope_context = self._scope_context, None
        await context.__aexit__(None, None, None)

    async def _rollback(self) -> None:
        if self._scope_context is None:
            return
        context, self._scope_context = self._scope_context, None
        error = _RollbackError()
        try:
            await context.__aexit__(type(error), error, error.__traceback__)
        except _RollbackError:
            pass

    async def _close(self) -> None:
        self._scope = None


class _RollbackError(Exception):
    """Private sentinel injected into the transaction context to force rollback."""


__all__ = ["PostgresDatabase", "PostgresUowFactory", "Scope"]
