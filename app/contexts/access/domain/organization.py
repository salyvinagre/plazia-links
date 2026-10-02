"""Canonical Identity organization identifier, independent of transport and persistence."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class OrganizationId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith("org_"):
            raise ValueError("Organization must be a canonical org_<uuidv7>")
        identifier = UUID(self.value[4:])
        if identifier.version != 7 or self.value != f"org_{identifier}":
            raise ValueError("Organization must be a canonical org_<uuidv7>")
