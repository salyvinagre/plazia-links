"""Operator commands use a separately supplied owner DSN; the API has no provisioning route."""

import argparse
import asyncio
from typing import Any

from shared_identity import OrganizationId
from shared_kernel import RequestContext
from shared_messaging import InProcessCommandBus

from app.contexts.access.application.commands.bind_organization.command import (
    BindOrganizationCommand,
)
from app.contexts.access.application.commands.bind_organization.handler import (
    BindOrganizationHandler,
)
from app.contexts.access.application.commands.disable_organization.command import (
    DisableOrganizationCommand,
)
from app.contexts.access.application.commands.disable_organization.handler import (
    DisableOrganizationHandler,
)
from app.platform.database import PostgresDatabase, PostgresUowFactory
from app.platform.persistence.schema import SchemaAuthority
from app.platform.settings import IdentitySettings, settings


async def provision(args: argparse.Namespace) -> None:
    identity = IdentitySettings()
    if not identity.issuer:
        raise ValueError("PLZL_IDENTITY_ISSUER is required")
    database = PostgresDatabase(settings.database_url.get_secret_value(), pooled=False)
    try:
        bus: InProcessCommandBus[Any] = InProcessCommandBus(
            handlers={
                BindOrganizationCommand: lambda uow: BindOrganizationHandler(
                    uow.scope.organizations
                ),
                DisableOrganizationCommand: lambda uow: DisableOrganizationHandler(
                    uow.scope.organizations
                ),
            },
            unit_of_work_factory=PostgresUowFactory(database),
        )
        org = OrganizationId(args.organization)
        command = (
            BindOrganizationCommand(identity.issuer, org, args.name)
            if args.action == "bind-organization"
            else DisableOrganizationCommand(identity.issuer, org)
        )
        await bus.dispatch(
            command,
            context=RequestContext.for_actor(
                actor_id="operator",
                actor_type="operator",
                request_id=RequestContext.new_request_id(),
                source_channel="cli",
            ),
        )
        print("Organization binding updated.")
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="plzl")
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("schema-prepare", "schema-finish", "schema-check"):
        actions.add_parser(name)
    bind = actions.add_parser("bind-organization")
    bind.add_argument("organization")
    bind.add_argument("--name", required=True)
    disable = actions.add_parser("disable-organization")
    disable.add_argument("organization")
    args = parser.parse_args()
    if args.action.startswith("schema-"):
        authority = SchemaAuthority(settings.database_url.get_secret_value())
        method = {
            "schema-prepare": authority.prepare,
            "schema-finish": authority.finish,
            "schema-check": authority.check,
        }[args.action]
        method()
        print("Schema authority verified.")
    else:
        asyncio.run(provision(args))


if __name__ == "__main__":
    main()
