"""Composition of access and link ports; no authorization or provisioning policy here."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import IdentitySettings
from app.contexts.access.adapters.browser_state import StoredBrowserState
from app.contexts.access.adapters.dpop import DPoPVerifier
from app.contexts.access.adapters.jwt_verifier import JwtVerifier
from app.contexts.access.adapters.oidc_client import OidcCodeClient
from app.contexts.access.adapters.redis_state import RedisState
from app.contexts.access.adapters.workspaces import SqlWorkspaceBindings
from app.contexts.access.application.browser import BrowserAuth
from app.contexts.access.application.ports import EphemeralStore, ProofVerifier, TokenVerifier
from app.contexts.access.application.workspaces import WorkspaceAccess, WorkspaceProvisioning
from app.contexts.access.contracts import Principal
from app.contexts.links.adapters.audit import SqlLinkAudit
from app.contexts.links.adapters.repository import SqlLinkRepository
from app.contexts.links.application.management import LinkManagement
from app.core.redis import get_redis


@dataclass(frozen=True)
class AccessRuntime:
    config: IdentitySettings
    tokens: TokenVerifier
    proofs: ProofVerifier
    browser: BrowserAuth

    @classmethod
    def build(cls, config: IdentitySettings, store: EphemeralStore | None = None) -> AccessRuntime:
        state = store if store is not None else RedisState(get_redis)
        tokens = JwtVerifier(config.issuer, config.audience, config.jwks_uri)
        client = OidcCodeClient(
            config.client_id,
            config.client_secret.get_secret_value(),
            config.authorization_endpoint,
            config.token_endpoint,
            config.redirect_uri,
            config.audience,
        )
        browser = BrowserAuth(
            config.client_id, config.session_ttl, client, tokens, StoredBrowserState(state)
        )
        return cls(config, tokens, DPoPVerifier(state), browser)


def workspace_access(db: AsyncSession) -> WorkspaceAccess:
    return WorkspaceAccess(SqlWorkspaceBindings(db))


def workspace_provisioning(db: AsyncSession, issuer: str) -> WorkspaceProvisioning:
    return WorkspaceProvisioning(SqlWorkspaceBindings(db), issuer)


def link_management(db: AsyncSession, principal: Principal) -> LinkManagement:
    return LinkManagement(principal, workspace_access(db), SqlLinkRepository(db), SqlLinkAudit(db))
