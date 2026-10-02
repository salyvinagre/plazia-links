"""Verified identity facts and the deliberately small Links authorization policy."""

from dataclasses import dataclass
from typing import Annotated, Literal

from shared_identity.canonical_ids import OrganizationId
from shared_kernel.fields import AnnotatedFields, CanonicalIdField, Text

Permission = Literal["links:read", "links:create", "links:update", "links:delete"]


class InvalidCredentialsError(Exception):
    """Untrusted or expired authentication evidence."""


class AccessUnavailableError(Exception):
    """A required authentication dependency is unavailable; fail closed."""


class AccessDeniedError(Exception):
    """Valid identity without the required local authority."""


@dataclass(frozen=True, slots=True)
class Principal:
    issuer: Annotated[str, Text()]
    subject: Annotated[str, Text()]
    client_id: Annotated[str, Text()]
    organization_id: Annotated[OrganizationId, CanonicalIdField(OrganizationId)]
    scopes: frozenset[str]
    expires_at: int
    token_id: str
    confirmation_jkt: str | None = None

    def __post_init__(self) -> None:
        AnnotatedFields.normalize(self)

    def require(self, permission: Permission) -> None:
        if permission not in self.scopes:
            raise AccessDeniedError(permission)

    def actor_details(self) -> dict[str, str]:
        return {
            "issuer": self.issuer,
            "subject": self.subject,
            "client_id": self.client_id,
            "organization_id": str(self.organization_id),
        }


@dataclass(frozen=True, slots=True)
class BrowserSession:
    principal: Principal
    csrf_token: str
    expires_at: int
