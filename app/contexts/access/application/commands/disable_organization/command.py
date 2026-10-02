from dataclasses import dataclass
from typing import Annotated

from shared_identity.canonical_ids import OrganizationId
from shared_kernel.fields import AnnotatedFields, CanonicalIdField, Text


@dataclass(frozen=True, slots=True)
class DisableOrganizationCommand:
    issuer: Annotated[str, Text()]
    organization_id: Annotated[OrganizationId, CanonicalIdField(OrganizationId)]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
