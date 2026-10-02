"""Published access boundary. No consumer depends on a context's internal layout."""

from typing import Protocol

from app.contexts.access.application.models import WorkspaceView as WorkspaceView
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


class WorkspaceResolver(Protocol):
    async def resolve(self, principal: Principal) -> WorkspaceView: ...
