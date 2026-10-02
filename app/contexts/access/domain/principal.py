"""Verified identity facts and the deliberately small Links authorization policy."""

from dataclasses import dataclass
from typing import Literal

Permission = Literal["read:links", "create:links", "update:links", "delete:links"]


class InvalidCredentialsError(Exception):
    """Untrusted or expired authentication evidence."""


class AccessUnavailableError(Exception):
    """A required authentication dependency is unavailable; fail closed."""


class AccessDeniedError(Exception):
    """Valid identity without the required local authority."""


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str
    client_id: str
    organization_id: str
    scopes: frozenset[str]
    expires_at: int
    token_id: str
    confirmation_jkt: str | None = None

    def require(self, permission: Permission) -> None:
        if permission not in self.scopes:
            raise AccessDeniedError(permission)

    def actor_details(self) -> dict[str, str]:
        return {
            "issuer": self.issuer,
            "subject": self.subject,
            "client_id": self.client_id,
            "organization_id": self.organization_id,
        }


@dataclass(frozen=True)
class BrowserSession:
    principal: Principal
    csrf_token: str
    expires_at: int
