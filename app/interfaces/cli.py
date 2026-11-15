"""Owner operator intents through the shared CLI and CQRS boundaries."""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Literal, cast
from uuid import UUID

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
from shared_kernel.fields import HttpOrigin

from app.contexts.access.contracts import BindOrganizationCommand, DisableOrganizationCommand
from app.platform.composition import Container
from app.platform.persistence.schema import SchemaAuthority, SchemaError
from app.platform.settings import OwnerSettings, PublicSettings

Action = Literal[
    "schema-prepare",
    "schema-finish",
    "schema-check",
    "release-qualify",
    "bind-organization",
    "disable-organization",
]
_HELP: dict[Action, str] = {
    "schema-prepare": "Verify the owner target before literal Flyway migration.",
    "schema-finish": "Verify the complete schema after Flyway migration.",
    "schema-check": "Read schema readiness without changing it.",
    "release-qualify": "Verify the selected preview database for a release operation.",
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
            options=(
                (CommandOption("--issuer", help="Configured organization issuer."),)
                if organization
                else ()
            )
            + (
                (
                    CommandOption("--name", required=True, help="Organization display name."),
                    CommandOption(
                        "--private-client",
                        multiple=True,
                        help="Client ID required to use private links.",
                    ),
                )
                if self.action == "bind-organization"
                else ()
            )
            + (
                (
                    CommandOption("--operation-id", required=True),
                    CommandOption("--control-revision", required=True, value_type=int),
                    CommandOption("--action", required=True, choices=("prepare", "verify")),
                )
                if self.action == "release-qualify"
                else ()
            ),
        )

    async def _invoke(self, invocation: CommandInvocation) -> int:
        try:
            if self.action == "release-qualify":
                self._qualify(invocation)
            elif self.action.startswith("schema-"):
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
                issuer = HttpOrigin().normalize(
                    invocation.optional_str("issuer") or identity.issuer, "Organization issuer"
                )
                if issuer not in (identity.issuer, *identity.machine_issuers):
                    raise CommandError("Organization issuer must be explicitly configured")
                org = OrganizationId(invocation.str("organization"))
                command = (
                    BindOrganizationCommand(
                        issuer,
                        org,
                        invocation.str("name"),
                        tuple(
                            str(value)
                            for value in cast(
                                tuple[object, ...], invocation.value("private_client")
                            )
                        ),
                    )
                    if self.action == "bind-organization"
                    else DisableOrganizationCommand(issuer, org)
                )
                async with Container.operator() as bus:
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

    @staticmethod
    def _qualify(invocation: CommandInvocation) -> None:
        settings = OwnerSettings()
        database_id = str(UUID(settings.database_id))
        operation_id = str(UUID(invocation.str("operation_id")))
        revision = invocation.optional_int("control_revision")
        if revision is None or revision < 0:
            raise CommandError("The control revision must be nonnegative")
        status = SchemaAuthority(settings.database_url.get_secret_value()).check()
        evidence = json.dumps(asdict(status), sort_keys=True, separators=(",", ":")).encode()
        result = {
            "version": 1,
            "repository": "salyvinagre/plazia-links",
            "command": "runtime",
            "operation_id": operation_id,
            "control_revision": revision,
            "action": invocation.str("action"),
            "outcome": "ready",
            "capabilities": [
                {
                    "name": "database",
                    "authority_id": database_id,
                    "revision": status.revision,
                    "evidence_digest": "sha256:" + hashlib.sha256(evidence).hexdigest(),
                }
            ],
        }
        print(json.dumps(result, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    return OperatorCli.router().run(argv)
