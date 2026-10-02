from dataclasses import dataclass

from shared_identity.canonical_ids import OrganizationId


@dataclass(frozen=True, slots=True)
class OrganizationDto:
    id: OrganizationId
    name: str
    is_active: bool
