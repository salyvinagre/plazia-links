"""Browser sign-in and session policy. No HTTP, serialization or framework dependencies."""

import hmac
import secrets
import time

from app.contexts.access.application.models import LoginAttempt
from app.contexts.access.application.ports import (
    AuthorizationCodeClient,
    BrowserStateStore,
    TokenVerifier,
)
from app.contexts.access.domain.principal import BrowserSession, InvalidCredentialsError


class BrowserAuth:
    SCOPES = "openid read:links create:links update:links delete:links"
    ATTEMPT_TTL = 600

    def __init__(
        self,
        client_id: str,
        session_ttl: int,
        client: AuthorizationCodeClient,
        tokens: TokenVerifier,
        store: BrowserStateStore,
    ) -> None:
        self._client_id = client_id
        self._session_ttl = session_ttl
        self._client = client
        self._tokens = tokens
        self._store = store

    async def begin(self) -> tuple[str, str]:
        verifier = secrets.token_urlsafe(48)
        state, handle, nonce = (secrets.token_urlsafe(32) for _ in range(3))
        attempt = LoginAttempt(verifier, nonce, int(time.time()) + self.ATTEMPT_TTL)
        await self._store.put_attempt(f"{handle}:{state}", attempt, self.ATTEMPT_TTL)
        return self._client.authorization_url(verifier, state, nonce, self.SCOPES), handle

    async def complete(self, handle: str, state: str, code: str) -> BrowserSession:
        if (
            not 32 <= len(handle) <= 128
            or not 32 <= len(state) <= 128
            or not 1 <= len(code) <= 4096
        ):
            raise InvalidCredentialsError
        # The port must consume the attempt atomically before exchanging the code.
        attempt = await self._store.take_attempt(f"{handle}:{state}")
        if attempt is None or attempt.expires_at <= time.time():
            raise InvalidCredentialsError
        tokens = await self._client.redeem(code, attempt.verifier)
        principal = await self._tokens.access_token(tokens.access_token)
        if principal.confirmation_jkt is not None or principal.client_id != self._client_id:
            raise InvalidCredentialsError
        identity_expiry = await self._tokens.id_token(
            tokens.id_token, self._client_id, attempt.nonce, tokens.access_token, principal
        )
        expiry = min(principal.expires_at, identity_expiry, int(time.time()) + self._session_ttl)
        if expiry <= time.time():
            raise InvalidCredentialsError
        return BrowserSession(principal, secrets.token_urlsafe(32), expiry)

    async def save(self, session: BrowserSession) -> str:
        handle = secrets.token_urlsafe(32)
        ttl = session.expires_at - int(time.time())
        if ttl <= 0:
            raise InvalidCredentialsError
        await self._store.put_session(handle, session, ttl)
        return handle

    async def session(self, handle: str) -> BrowserSession:
        if not 32 <= len(handle) <= 128:
            raise InvalidCredentialsError
        session = await self._store.get_session(handle)
        if session is None:
            raise InvalidCredentialsError
        if min(session.expires_at, session.principal.expires_at) <= time.time():
            await self.logout(handle)
            raise InvalidCredentialsError
        return session

    async def logout(self, handle: str) -> None:
        if handle:
            await self._store.remove_session(handle)

    @staticmethod
    def verify_csrf(session: BrowserSession, supplied: str) -> None:
        if not supplied or not hmac.compare_digest(session.csrf_token.encode(), supplied.encode()):
            raise InvalidCredentialsError
