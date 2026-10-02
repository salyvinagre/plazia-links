"""Service-local composition for the Identity boundary; no shared implementation imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.contexts.access.contracts import Principal
    from app.contexts.links.application.management import LinkManagement

from dataclasses import dataclass

from app.config import IdentitySettings
from app.contexts.access.adapters.browser import BrowserAuth
from app.contexts.access.adapters.dpop import DPoPVerifier
from app.contexts.access.adapters.jwt_verifier import JwtVerifier
from app.contexts.access.adapters.redis_state import RedisState
from app.contexts.access.application.ports import EphemeralStore
from app.core.redis import get_redis


@dataclass(frozen=True)
class AccessRuntime:
    config: IdentitySettings
    tokens: JwtVerifier
    proofs: DPoPVerifier
    browser: BrowserAuth

    @classmethod
    def build(cls, config: IdentitySettings, store: EphemeralStore | None = None) -> AccessRuntime:
        state = store if store is not None else RedisState(get_redis)
        tokens = JwtVerifier(config.issuer, config.audience, config.jwks_uri)
        return cls(config, tokens, DPoPVerifier(state), BrowserAuth(config, tokens, state))


async def link_management(db: AsyncSession, principal: Principal) -> LinkManagement:
    """The sole composition entry point for request-scoped link management."""
    from app.contexts.access.adapters.workspaces import WorkspaceAccess
    from app.contexts.links.adapters.repository import SqlLinkRepository
    from app.contexts.links.application.management import LinkManagement

    workspace = await WorkspaceAccess.resolve(db, principal)
    return LinkManagement(principal, SqlLinkRepository(db, workspace.id, principal))
