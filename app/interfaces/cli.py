"""Owner operator intents through the shared CLI and CQRS boundaries."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from plazia_cli.commands import (
    CommandArgument,
    CommandDefinition,
    CommandError,
    CommandInvocation,
    CommandOption,
)
from plazia_cli.routing import Route, Router
from shared_identity import OrganizationId
from shared_kernel import RequestContext

from app.contexts.access.contracts import BindOrganizationCommand, DisableOrganizationCommand
from app.platform.composition import operator_commands
from app.platform.persistence.schema import SchemaAuthority, SchemaError
from app.platform.settings import OwnerSettings, PublicSettings

Action = Literal[
    "schema-prepare", "schema-finish", "schema-check", "bind-organization", "disable-organization"
]
_HELP: dict[Action, str] = {
    "schema-prepare": "Verify the owner target before literal Flyway migration.",
    "schema-finish": "Verify the complete schema after Flyway migration.",
    "schema-check": "Read schema readiness without changing it.",
    "bind-organization": "Enable an Identity organization using the owner credential.",
    "disable-organization": "Revoke management access for an organization.",
}


@dataclass(frozen=True, slots=True)
class OperatorCli:
    action: Action

    @classmethod
    def router(cls) -> Router:
        return Router.create(
            prog="plazia-links",
            description="Owner schema and organization operations.",
            groups=(),
            routes=(Route((action,), help, cls(action).define()) for action, help in _HELP.items()),
        )

    def define(self) -> CommandDefinition:
        organization = self.action in {"bind-organization", "disable-organization"}
        return CommandDefinition(
            name=self.action,
            prog=f"plazia-links {self.action}",
            help=_HELP[self.action],
            handler=self._invoke,
            arguments=(CommandArgument("organization"),) if organization else (),
            options=(CommandOption("--name", required=True, help="Organization display name."),)
            if self.action == "bind-organization"
            else (),
        )

    async def _invoke(self, invocation: CommandInvocation) -> int:
        try:
            if self.action.startswith("schema-"):
                authority = SchemaAuthority(OwnerSettings().database_url.get_secret_value())
                method = {
                    "schema-prepare": authority.prepare,
                    "schema-finish": authority.finish,
                    "schema-check": authority.check,
                }[self.action]
                method()
                print("Schema authority verified.")
            else:
                identity = PublicSettings()
                if not identity.issuer:
                    raise CommandError("PLZK_IDENTITY_ISSUER is required")
                org = OrganizationId(invocation.str("organization"))
                command = (
                    BindOrganizationCommand(identity.issuer, org, invocation.str("name"))
                    if self.action == "bind-organization"
                    else DisableOrganizationCommand(identity.issuer, org)
                )
                async with operator_commands() as bus:
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
        except CommandError:
            raise
        except SchemaError as error:
            raise CommandError(str(error)) from error
        except Exception as error:
            raise CommandError(
                "Operator action failed; check configuration and target readiness."
            ) from error
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    return OperatorCli.router().run(argv)
