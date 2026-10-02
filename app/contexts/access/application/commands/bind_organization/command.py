from dataclasses import dataclass
from typing import Annotated

from shared_identity.canonical_ids import OrganizationId
from shared_kernel.fields import AnnotatedFields, CanonicalIdField, Length, Text


@dataclass(frozen=True, slots=True)
class BindOrganizationCommand:
    issuer: Annotated[str, Text()]
    organization_id: Annotated[OrganizationId, CanonicalIdField(OrganizationId)]
    name: Annotated[str, Text(), Length(maximum=100)]

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)
