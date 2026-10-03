"""The composition root binds application intent handlers to shared dispatch/UoW."""

import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, dataclass
from typing import Any, Protocol, cast

from dependency_injector import containers, providers
from shared_identity import OrganizationId
from shared_messaging import InProcessCommandBus, InProcessQueryBus
from shared_messaging.command_bus import CommandEnvelope, CommandHandlerResolver
from shared_messaging.invocation import Invocation
from shared_messaging.query_bus import QueryEnvelope
from shared_messaging.unit_of_work import CommandUnitOfWorkFactory
from shared_observability.telemetry import TelemetryService

from app.contexts.access.application.authorization import (
    AuthorizationAttempt,
    OrganizationAuthority,
)
from app.contexts.access.application.queries.resolve_organization.handler import (
    ResolveOrganizationHandler,
)
from app.contexts.access.application.queries.resolve_organization.query import (
    ResolveOrganizationQuery,
)
from app.contexts.access.contracts import Principal
from app.contexts.links.application.commands.create_link.command import CreateLinkCommand
from app.contexts.links.application.commands.create_link.handler import CreateLinkHandler
from app.contexts.links.application.commands.delete_link.command import DeleteLinkCommand
from app.contexts.links.application.commands.delete_link.handler import DeleteLinkHandler
from app.contexts.links.application.commands.delete_links.command import DeleteLinksCommand
from app.contexts.links.application.commands.delete_links.handler import DeleteLinksHandler
from app.contexts.links.application.commands.delete_pool.command import DeletePoolCommand
from app.contexts.links.application.commands.delete_pool.handler import DeletePoolHandler
from app.contexts.links.application.commands.rename_pool.command import RenamePoolCommand
from app.contexts.links.application.commands.rename_pool.handler import RenamePoolHandler
from app.contexts.links.application.commands.reserve_pool.command import ReservePoolCommand
from app.contexts.links.application.commands.reserve_pool.handler import ReservePoolHandler
from app.contexts.links.application.commands.subscribe_link.command import SubscribeLinkCommand
from app.contexts.links.application.commands.subscribe_link.handler import SubscribeLinkHandler
from app.contexts.links.application.commands.update_link.command import UpdateLinkCommand
from app.contexts.links.application.commands.update_link.handler import UpdateLinkHandler
from app.contexts.links.application.dto.links import CommandResultDto
from app.contexts.links.application.queries.get_link.handler import GetLinkHandler
from app.contexts.links.application.queries.get_link.query import GetLinkQuery
from app.contexts.links.application.queries.get_pool.handler import GetPoolHandler
from app.contexts.links.application.queries.get_pool.query import GetPoolQuery
from app.contexts.links.application.queries.list_links.handler import ListLinksHandler
from app.contexts.links.application.queries.list_links.query import ListLinksQuery
from app.contexts.links.application.queries.list_pools.handler import ListPoolsHandler
from app.contexts.links.application.queries.list_pools.query import ListPoolsQuery
from app.contexts.links.application.queries.resolve_link.handler import ResolveLinkHandler
from app.contexts.links.application.queries.resolve_link.query import ResolveLinkQuery
from app.platform.database import Scope


class Database(Protocol):
    def scope(
        self, organization_id: OrganizationId | None = None, *, readonly: bool = True
    ) -> AbstractAsyncContextManager[Scope]: ...


COMMANDS = {
    CreateLinkCommand: CreateLinkHandler,
    UpdateLinkCommand: UpdateLinkHandler,
    DeleteLinkCommand: DeleteLinkHandler,
    DeleteLinksCommand: DeleteLinksHandler,
    DeletePoolCommand: DeletePoolHandler,
    RenamePoolCommand: RenamePoolHandler,
    ReservePoolCommand: ReservePoolHandler,
    SubscribeLinkCommand: SubscribeLinkHandler,
}
QUERIES = {
    GetLinkQuery: GetLinkHandler,
    GetPoolQuery: GetPoolHandler,
    ListLinksQuery: ListLinksHandler,
    ListPoolsQuery: ListPoolsHandler,
    ResolveLinkQuery: ResolveLinkHandler,
    ResolveOrganizationQuery: ResolveOrganizationHandler,
}
PERMISSIONS = {
    CreateLinkCommand: "links:create",
    UpdateLinkCommand: "links:update",
    DeleteLinkCommand: "links:delete",
    DeleteLinksCommand: "links:delete",
    DeletePoolCommand: "links:delete",
    RenamePoolCommand: "links:update",
    ReservePoolCommand: "links:create",
    GetLinkQuery: "links:read",
    GetPoolQuery: "links:read",
    ListLinksQuery: "links:read",
    ListPoolsQuery: "links:read",
    ResolveOrganizationQuery: "links:read",
}


def handler(kind: type[Any], scope: Scope, telemetry: TelemetryService | None = None) -> Any:
    if kind is ResolveOrganizationHandler:
        return kind(scope.access)
    if kind in {SubscribeLinkHandler, ResolveLinkHandler}:
        return kind(scope.links)
    if kind is UpdateLinkHandler:
        return kind(scope.links, scope.access, telemetry)
    return kind(scope.links, scope.access)


@dataclass(frozen=True, slots=True)
class ScopedQueryHandler:
    database: Database
    kind: type[Any]

    async def execute(self, query: object, *, context: Invocation | None = None) -> Any:
        actor = getattr(query, "actor", None)
        async with self.database.scope(
            actor.organization_id if isinstance(actor, Principal) else None
        ) as scope:
            return await handler(self.kind, scope).execute(query, context=context)


@dataclass(frozen=True, slots=True)
class ScopedCommandHandler:
    kind: type[Any]
    scope: Scope
    telemetry: TelemetryService | None = None

    async def execute(self, command: Any, *, context: Invocation) -> Any:
        # Binding revocation and capabilities apply to replay as well as first execution.
        await self.scope.access.require(command.actor, cast(Any, PERMISSIONS[type(command)]))
        key = context.operation_context.idempotency_key
        if not key:
            raise ValueError("Mutation requires an idempotency key")
        payload = asdict(command)
        del payload["actor"]
        fingerprint = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                default=lambda value: (
                    sorted(value) if isinstance(value, (set, frozenset)) else str(value)
                ),
            ).encode()
        ).hexdigest()
        action = type(command).__name__
        saved = await self.scope.links.replay(command.actor, action, key, fingerprint)
        if saved is not None:
            return saved
        result = await handler(self.kind, self.scope, self.telemetry).execute(
            command, context=context
        )
        await self.scope.links.remember(command.actor, action, key, result)
        return CommandResultDto(result)


class Container(containers.DeclarativeContainer):
    database: providers.Dependency[Database] = providers.Dependency()
    uow_factory: providers.Dependency[CommandUnitOfWorkFactory] = providers.Dependency()
    authority: providers.Dependency[OrganizationAuthority] = providers.Dependency()


def build_buses(
    database: Database,
    uow_factory: CommandUnitOfWorkFactory,
    authority: OrganizationAuthority,
    telemetry: TelemetryService | None = None,
) -> tuple[InProcessCommandBus[Any], InProcessQueryBus]:
    container = Container(database=database, uow_factory=uow_factory, authority=authority)

    async def authorize(envelope: CommandEnvelope | QueryEnvelope[Any]) -> None:
        intent = envelope.command if isinstance(envelope, CommandEnvelope) else envelope.query
        await container.authority().require(
            AuthorizationAttempt(
                getattr(intent, "actor"), cast(Any, PERMISSIONS[type(intent)]), envelope.context
            )
        )

    def command_resolver(intent: type[Any], kind: type[Any]) -> CommandHandlerResolver:
        return lambda uow: (
            ScopedCommandHandler(kind, cast(Scope, uow.scope), telemetry)
            if intent in PERMISSIONS
            else handler(kind, cast(Scope, uow.scope))
        )

    command_bus: InProcessCommandBus[Any] = InProcessCommandBus(
        handlers={intent: command_resolver(intent, kind) for intent, kind in COMMANDS.items()},
        unit_of_work_factory=container.uow_factory(),
        authorizers={intent: authorize for intent in COMMANDS if intent in PERMISSIONS},
    )

    def query_resolver(kind: type[Any]) -> Callable[[QueryEnvelope[Any]], ScopedQueryHandler]:
        def resolve(envelope: QueryEnvelope[Any]) -> ScopedQueryHandler:
            return ScopedQueryHandler(container.database(), kind)

        return resolve

    query_bus = InProcessQueryBus(
        handlers={intent: query_resolver(kind) for intent, kind in QUERIES.items()},
        authorizers={intent: authorize for intent in QUERIES if intent in PERMISSIONS},
    )
    return command_bus, query_bus
