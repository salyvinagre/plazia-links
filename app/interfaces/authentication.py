"""HTTP authentication adapters. Browser cookies are never API bearer credentials."""

from typing import Annotated

from fastapi import HTTPException, Request, Security
from fastapi.security import OAuth2AuthorizationCodeBearer

from app.contexts.access.contracts import (
    AccessUnavailableError,
    BrowserSession,
    InvalidCredentialsError,
    Principal,
)
from app.platform.access import AccessRuntime
from app.platform.settings import IdentitySettings

_config = IdentitySettings()
oauth = OAuth2AuthorizationCodeBearer(
    authorizationUrl=_config.authorization_endpoint,
    tokenUrl=_config.token_endpoint,
    scopes={
        "links:read": "Read links and pools",
        "links:create": "Create links and reserve pools",
        "links:update": "Activate and edit links",
        "links:delete": "Delete links",
    },
    auto_error=False,
)


def runtime(request: Request) -> AccessRuntime:
    value = request.app.state.access
    if not isinstance(value, AccessRuntime):
        raise RuntimeError("Identity runtime is not configured")
    return value


def authentication_error(scheme: str = "Bearer") -> HTTPException:
    challenge = f'{scheme} realm="plazia-links", error="invalid_token"'
    if scheme == "DPoP":
        challenge = 'DPoP realm="plazia-links", error="invalid_dpop_proof", algs="ES256 RS256"'
    return HTTPException(
        401,
        "invalid_credentials",
        headers={"WWW-Authenticate": challenge, "Cache-Control": "no-store"},
    )


async def api_principal(
    request: Request, _credential: Annotated[str | None, Security(oauth)]
) -> Principal:
    headers = request.headers.getlist("authorization")
    if len(headers) != 1:
        raise authentication_error()
    parts = headers[0].split()
    if len(parts) != 2 or parts[0].lower() not in {"bearer", "dpop"}:
        raise authentication_error()
    scheme = "DPoP" if parts[0].lower() == "dpop" else "Bearer"
    auth = runtime(request)
    try:
        principal = await auth.tokens.access_token(parts[1])
        proofs = request.headers.getlist("dpop")
        if principal.confirmation_jkt is not None:
            if scheme != "DPoP" or len(proofs) != 1:
                raise InvalidCredentialsError
            path = request.scope.get("raw_path", request.url.path.encode()).decode("ascii")
            await auth.proofs.verify(
                proofs[0],
                parts[1],
                principal.confirmation_jkt,
                request.method,
                auth.config.public_base_url.rstrip("/") + path,
            )
        elif scheme != "Bearer" or proofs:
            raise InvalidCredentialsError
        return principal
    except InvalidCredentialsError as exc:
        raise authentication_error(scheme) from exc
    except AccessUnavailableError as exc:
        raise HTTPException(
            503, "identity_unavailable", headers={"Cache-Control": "no-store"}
        ) from exc


async def browser_session(request: Request) -> BrowserSession:
    auth = runtime(request)
    try:
        return await auth.browser.session(request.cookies.get(auth.config.session_cookie, ""))
    except InvalidCredentialsError as exc:
        # Location is fixed, never a caller-controlled return URL.
        raise HTTPException(
            303, headers={"Location": "/login", "Cache-Control": "no-store"}
        ) from exc
    except AccessUnavailableError as exc:
        raise HTTPException(
            503, "session_store_unavailable", headers={"Cache-Control": "no-store"}
        ) from exc


def csrf(request: Request, session: BrowserSession, token: str) -> None:
    origin = request.headers.get("origin")
    expected = runtime(request).config.public_base_url.rstrip("/")
    if origin is not None and origin.rstrip("/") != expected:
        raise HTTPException(403, "csrf_rejected")
    try:
        runtime(request).browser.verify_csrf(session, token)
    except InvalidCredentialsError as exc:
        raise HTTPException(403, "csrf_rejected") from exc
