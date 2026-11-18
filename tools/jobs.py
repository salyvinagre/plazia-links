"""Bind Links jobs to the admitted runtime image and database."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn

from plazia_tooling.release.config import ReleaseSelection
from plazia_tooling.release.hooks import ReleaseHookProvider, register_provider


@dataclass(frozen=True, slots=True)
class Job(ReleaseHookProvider):
    name: str
    options: tuple[str, ...] = ()
    service = "activation-email"

    @property
    def provider(self) -> str:
        return self.name

    @property
    def arguments(self) -> tuple[str, ...]:
        return ("python", "-m", "worker.run", *self.options)

    def capture_operation(
        self, *, selection: ReleaseSelection, environment: Mapping[str, str], **_: object
    ) -> tuple[dict[str, str], dict[str, str]]:
        return (
            {
                "repository": "salyvinagre/plazia-links",
                "selector": "PLZK_IMAGE",
                "image": environment["PLZK_IMAGE"],
            },
            {
                "environment": selection.environment,
                "database_id": environment["PLZK_SCHEMA_DATABASE_ID"],
            },
        )

    def secret_selectors(self, **_: object) -> tuple[str, ...]:
        return ()

    generated_selectors = secret_selectors

    async def execute(self, **_: object) -> NoReturn:
        raise ValueError("Links jobs run through the release controller.")


register_provider(Job("links-activation-email"))
register_provider(Job("links-subscription-cleanup", ("--cleanup",)))
