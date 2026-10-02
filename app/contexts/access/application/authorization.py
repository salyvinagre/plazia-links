"""Organization authority is separate from OAuth client capabilities and local binding."""

from dataclasses import dataclass
from typing import Protocol

from shared_messaging.invocation import Invocation

from app.contexts.access.domain.principal import Permission, Principal


@dataclass(frozen=True, slots=True)
class AuthorizationAttempt:
    actor: Principal
    permission: Permission
    context: Invocation | None


class OrganizationAuthority(Protocol):
    async def require(self, attempt: AuthorizationAttempt) -> None: ...
