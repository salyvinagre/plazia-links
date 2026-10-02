"""Confidential OIDC code flow and opaque browser sessions; tokens remain server-side."""

import hmac
import secrets
import time
from urllib.parse import quote_plus, urlencode

import httpx
from oauthlib.oauth2 import WebApplicationClient
from oauthlib.oauth2.rfc6749.errors import OAuth2Error
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.config import IdentitySettings
from app.contexts.access.adapters.jwt_verifier import JwtVerifier
from app.contexts.access.application.ports import EphemeralStore
from app.contexts.access.domain.principal import (
    AccessUnavailableError,
    BrowserSession,
    InvalidCredentialsError,
)


class LoginAttempt(BaseModel):
    verifier: str
    nonce: str
    expires_at: int


class BrowserAuth:
    SCOPES = "openid read:links create:links update:links delete:links"
    ATTEMPT_TTL = 600

    def __init__(
        self, config: IdentitySettings, tokens: JwtVerifier, store: EphemeralStore
    ) -> None:
        self.config = config
        self._tokens = tokens
        self._store = store
        self._sessions = TypeAdapter(BrowserSession)

    async def begin(self) -> tuple[str, str]:
        client = WebApplicationClient(self.config.client_id)
        verifier = str(client.create_code_verifier(64))
        challenge = str(client.create_code_challenge(verifier, "S256"))
        state, handle, nonce = (secrets.token_urlsafe(32) for _ in range(3))
        attempt = LoginAttempt(
            verifier=verifier, nonce=nonce, expires_at=int(time.time()) + self.ATTEMPT_TTL
        )
        await self._store.put(
            "login", f"{handle}:{state}", attempt.model_dump_json(), self.ATTEMPT_TTL
        )
        # All endpoint URLs come from deployment configuration, not discovery or request Host.
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": self.SCOPES,
            "resource": self.config.audience,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return self.config.authorization_endpoint + "?" + urlencode(params), handle

    async def complete(self, handle: str, state: str, code: str) -> BrowserSession:
        if (
            not 32 <= len(handle) <= 128
            or not 32 <= len(state) <= 128
            or not 1 <= len(code) <= 4096
        ):
            raise InvalidCredentialsError
        # GETDEL consumes the browser-bound transaction even if redemption later fails.
        raw = await self._store.take("login", f"{handle}:{state}")
        if raw is None:
            raise InvalidCredentialsError
        try:
            attempt = LoginAttempt.model_validate_json(raw)
        except ValidationError as exc:
            raise InvalidCredentialsError from exc
        if attempt.expires_at <= time.time():
            raise InvalidCredentialsError
        client = WebApplicationClient(self.config.client_id)
        body = client.prepare_request_body(
            code=code,
            redirect_uri=self.config.redirect_uri,
            code_verifier=attempt.verifier,
            include_client_id=False,
            resource=self.config.audience,
        )
        try:
            async with httpx.AsyncClient(
                timeout=5, follow_redirects=False, trust_env=False
            ) as http:
                response = await http.post(
                    self.config.token_endpoint,
                    content=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    auth=httpx.BasicAuth(
                        quote_plus(self.config.client_id, safe=""),
                        quote_plus(self.config.client_secret.get_secret_value(), safe=""),
                    ),
                )
            if response.status_code >= 500:
                raise AccessUnavailableError
            if response.status_code != 200 or len(response.content) > 65536:
                raise InvalidCredentialsError
            token = client.parse_request_body_response(response.text)
        except httpx.HTTPError as exc:
            raise AccessUnavailableError from exc
        except (OAuth2Error, ValueError) as exc:
            raise InvalidCredentialsError from exc
        if not isinstance(token, dict):
            raise InvalidCredentialsError
        access_token = token.get("access_token")
        id_token = token.get("id_token")
        if (
            not isinstance(access_token, str)
            or not isinstance(id_token, str)
            or str(token.get("token_type", "")).lower() != "bearer"
        ):
            raise InvalidCredentialsError
        principal = await self._tokens.access_token(access_token)
        if principal.confirmation_jkt is not None or principal.client_id != self.config.client_id:
            # This browser client is explicitly registered for unbound tokens; never downgrade DPoP.
            raise InvalidCredentialsError
        identity_expiry = await self._tokens.id_token(
            id_token, self.config.client_id, attempt.nonce, access_token, principal
        )
        expiry = min(
            principal.expires_at, identity_expiry, int(time.time()) + self.config.session_ttl
        )
        if expiry <= time.time():
            raise InvalidCredentialsError
        return BrowserSession(principal, secrets.token_urlsafe(32), expiry)

    async def save(self, session: BrowserSession) -> str:
        handle = secrets.token_urlsafe(32)
        ttl = session.expires_at - int(time.time())
        if ttl <= 0:
            raise InvalidCredentialsError
        await self._store.put("session", handle, self._sessions.dump_json(session).decode(), ttl)
        return handle

    async def session(self, handle: str) -> BrowserSession:
        if not 32 <= len(handle) <= 128:
            raise InvalidCredentialsError
        raw = await self._store.get("session", handle)
        if raw is None:
            raise InvalidCredentialsError
        try:
            session = self._sessions.validate_json(raw)
        except ValidationError as exc:
            raise InvalidCredentialsError from exc
        if min(session.expires_at, session.principal.expires_at) <= time.time():
            await self.logout(handle)
            raise InvalidCredentialsError
        return session

    async def logout(self, handle: str) -> None:
        if handle:
            await self._store.remove("session", handle)

    @staticmethod
    def verify_csrf(session: BrowserSession, supplied: str) -> None:
        if not supplied or not hmac.compare_digest(session.csrf_token.encode(), supplied.encode()):
            raise InvalidCredentialsError
