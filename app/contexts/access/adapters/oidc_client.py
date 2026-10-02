"""OAuthlib/HTTPX transport adapter for the configured confidential browser client."""

from urllib.parse import quote_plus, urlencode

import httpx
from oauthlib.oauth2 import WebApplicationClient
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

from app.contexts.access.application.dto.session import TokenPairDto
from app.contexts.access.domain.principal import AccessUnavailableError, InvalidCredentialsError


class OidcCodeClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        authorization_endpoint: str,
        token_endpoint: str,
        redirect_uri: str,
        audience: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._authorization_endpoint = authorization_endpoint
        self._token_endpoint = token_endpoint
        self._redirect_uri = redirect_uri
        self._audience = audience

    def authorization_url(self, verifier: str, state: str, nonce: str, scopes: str) -> str:
        client = WebApplicationClient(self._client_id)
        challenge = str(client.create_code_challenge(verifier, "S256"))
        return (
            self._authorization_endpoint
            + "?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": self._client_id,
                    "redirect_uri": self._redirect_uri,
                    "scope": scopes,
                    "resource": self._audience,
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    async def redeem(self, code: str, verifier: str) -> TokenPairDto:
        client = WebApplicationClient(self._client_id)
        body = client.prepare_request_body(
            code=code,
            redirect_uri=self._redirect_uri,
            code_verifier=verifier,
            include_client_id=False,
            resource=self._audience,
        )
        try:
            async with httpx.AsyncClient(
                timeout=5, follow_redirects=False, trust_env=False
            ) as http:
                response = await http.post(
                    self._token_endpoint,
                    content=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    auth=httpx.BasicAuth(
                        quote_plus(self._client_id, safe=""),
                        quote_plus(self._client_secret, safe=""),
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
        access_token, id_token = token.get("access_token"), token.get("id_token")
        if (
            not isinstance(access_token, str)
            or not isinstance(id_token, str)
            or str(token.get("token_type", "")).lower() != "bearer"
        ):
            raise InvalidCredentialsError
        return TokenPairDto(access_token, id_token)
