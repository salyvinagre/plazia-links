from dataclasses import dataclass
from typing import Annotated

from shared_identity.canonical_ids import OrganizationId
from shared_kernel.fields import AnnotatedFields, CanonicalIdField, Length, Text


@dataclass(frozen=True, slots=True)
class BindOrganizationCommand:
    issuer: Annotated[str, Text()]
    organization_id: Annotated[OrganizationId, CanonicalIdField(OrganizationId)]
    name: Annotated[str, Text(), Length(maximum=100)]
    workloads: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
        if len(self.workloads) > 16 or any(
            not value.strip() or len(value) > 2048 for value in self.workloads
        ):
            raise ValueError("Workload clients must be bounded nonempty identifiers")
