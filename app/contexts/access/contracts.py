"""Published Identity facts and local tenant access contract."""

from typing import Protocol

from app.contexts.access.application.commands.bind_organization.command import (
    BindOrganizationCommand as BindOrganizationCommand,
)
from app.contexts.access.application.commands.disable_organization.command import (
    DisableOrganizationCommand as DisableOrganizationCommand,
)
from app.contexts.access.application.dto.organization import OrganizationDto as OrganizationDto
from app.contexts.access.application.queries.resolve_organization.query import (
    ResolveOrganizationQuery as ResolveOrganizationQuery,
)
from app.contexts.access.domain.principal import (
    AccessDeniedError as AccessDeniedError,
)
from app.contexts.access.domain.principal import (
    AccessUnavailableError as AccessUnavailableError,
)
from app.contexts.access.domain.principal import (
    BrowserSession as BrowserSession,
)
from app.contexts.access.domain.principal import (
    InvalidCredentialsError as InvalidCredentialsError,
)
from app.contexts.access.domain.principal import (
    Permission as Permission,
)
from app.contexts.access.domain.principal import (
    Principal as Principal,
)


class OrganizationAccessPort(Protocol):
    async def require(self, principal: Principal, permission: Permission) -> OrganizationDto: ...
    async def resolve(self, principal: Principal) -> OrganizationDto: ...
