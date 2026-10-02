"""Identity runtime composition; no local identity replica or tenant inference."""

from dataclasses import dataclass

from app.contexts.access.adapters.browser_state import StoredBrowserState
from app.contexts.access.adapters.dpop import DPoPVerifier
from app.contexts.access.adapters.jwt_verifier import JwtVerifier
from app.contexts.access.adapters.oidc_client import OidcCodeClient
from app.contexts.access.adapters.redis_state import RedisState
from app.contexts.access.application.ports.session import (
    EphemeralStore,
    ProofVerifier,
    TokenVerifier,
)
from app.contexts.access.application.workflows.browser import BrowserAuth
from app.platform.redis import get_redis
from app.platform.settings import IdentitySettings


@dataclass(frozen=True, slots=True)
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
