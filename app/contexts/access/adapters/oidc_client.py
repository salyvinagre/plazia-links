"""Links browser-grant port over the shared OAuth client and PKCE values."""

from dataclasses import replace
from urllib.parse import urlencode

from plazia_authlib.authn.client import PlaziaIdentity
from plazia_authlib.authn.errors import IdentityApiError, IdentityTransportError
from plazia_authlib.authn.oauth import OAuthAuthorizationArtifacts
from pydantic import ValidationError
from shared_http import HttpRequest, HttpResponse

from app.contexts.access.application.dto.session import TokenPairDto
from app.contexts.access.domain.principal import AccessUnavailableError, InvalidCredentialsError


class OidcCodeClient:
    def __init__(
        self, client_id: str, client_secret: str, issuer: str, redirect_uri: str, audience: str
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._issuer = issuer
        self._redirect_uri = redirect_uri
        self._audience = audience

    def authorization_url(self, verifier: str, state: str, nonce: str, scopes: str) -> str:
        artifacts = OAuthAuthorizationArtifacts.from_values(state=state, code_verifier=verifier)
        return (
            self._issuer.rstrip("/")
            + "/oauth2/auth?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": self._client_id,
                    "redirect_uri": self._redirect_uri,
                    "scope": scopes,
                    "resource": self._audience,
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": artifacts.code_challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    async def redeem(self, code: str, verifier: str) -> TokenPairDto:
        try:
            async with PlaziaIdentity(base_url=self._issuer, timeout=5) as identity:
                tokens = await identity.tokens.authorization_code(
                    client_id=self._client_id,
                    client_secret=self._client_secret,
                    code=code,
                    redirect_uri=self._redirect_uri,
                    code_verifier=verifier,
                    resource=self._audience,
                    authority=self,
                )
        except IdentityApiError as error:
            if error.detail.status_code >= 500:
                raise AccessUnavailableError from error
            raise InvalidCredentialsError from error
        except IdentityTransportError as error:
            raise AccessUnavailableError from error
        except (ValueError, ValidationError) as error:
            raise InvalidCredentialsError from error
        if tokens.token_type.lower() != "bearer" or not tokens.id_token:
            raise InvalidCredentialsError
        return TokenPairDto(tokens.access_token, tokens.id_token)

    async def authorize(self, request: HttpRequest) -> HttpRequest:
        if request.method != "POST" or request.url != self._issuer.rstrip("/") + "/oauth2/token":
            raise InvalidCredentialsError
        return replace(request, max_response_bytes=65536)

    def consume_response(self, response: HttpResponse) -> bool:
        return False
