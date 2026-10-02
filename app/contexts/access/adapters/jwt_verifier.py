"""Identity's RS256/RFC 9068 profile, using PyJWT for all signature validation."""

import asyncio
import base64
import hashlib
import hmac
import threading
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import jwt

from app.contexts.access.domain.principal import (
    AccessUnavailableError,
    InvalidCredentialsError,
    Principal,
)


class JwtVerifier:
    def __init__(self, issuer: str, audience: str, jwks_uri: str) -> None:
        self.issuer = issuer
        self.audience = audience
        # Do not cache individual keys forever. Unknown-kid refreshes are throttled.
        self._keys = jwt.PyJWKClient(
            jwks_uri, cache_keys=False, lifespan=300, timeout=5, cooldown_duration=5
        )
        self._key_lock = threading.Lock()

    @staticmethod
    def _text(claims: Mapping[str, Any], name: str) -> str:
        value = claims.get(name)
        if not isinstance(value, str) or not value or len(value) > 1024:
            raise InvalidCredentialsError
        return value

    def _decode(self, token: str, audience: str, access: bool) -> dict[str, Any]:
        if len(token) > 16384 or token.count(".") != 2:
            raise InvalidCredentialsError
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or header.get("crit"):
                raise InvalidCredentialsError
            expected_types = (
                {"at+jwt", "application/at+jwt"} if access else {None, "JWT", "application/jwt"}
            )
            if header.get("typ") not in expected_types:
                raise InvalidCredentialsError
            if any(key in header for key in ("jku", "x5u", "jwk")):
                raise InvalidCredentialsError
            self._text(header, "kid")
            with self._key_lock:
                key = self._keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=audience,
                leeway=5,
                options={"require": ["iss", "aud", "sub", "exp", "iat"]},
            )
            if type(claims["exp"]) is not int or type(claims["iat"]) is not int:
                raise InvalidCredentialsError
            if claims["exp"] <= claims["iat"]:
                raise InvalidCredentialsError
            self._text(claims, "sub")
            return claims
        except jwt.PyJWKClientConnectionError as exc:
            raise AccessUnavailableError from exc
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise InvalidCredentialsError from exc

    async def access_token(self, token: str) -> Principal:
        claims = await asyncio.to_thread(self._decode, token, self.audience, True)
        try:
            organization = self._text(claims, "org")
            if not organization.startswith("org_"):
                raise InvalidCredentialsError
            identifier = UUID(organization[4:])
            if identifier.version != 7 or organization != f"org_{identifier}":
                raise InvalidCredentialsError
            scopes = claims.get("scope", "")
            if not isinstance(scopes, str):
                raise InvalidCredentialsError
            confirmation = claims.get("cnf")
            jkt = None
            if confirmation is not None:
                if not isinstance(confirmation, dict) or set(confirmation) != {"jkt"}:
                    raise InvalidCredentialsError
                jkt = self._text(confirmation, "jkt")
            return Principal(
                issuer=self.issuer,
                subject=self._text(claims, "sub"),
                client_id=self._text(claims, "client_id"),
                organization_id=organization,
                scopes=frozenset(scopes.split()),
                expires_at=claims["exp"],
                token_id=self._text(claims, "jti"),
                confirmation_jkt=jkt,
            )
        except (ValueError, TypeError) as exc:
            raise InvalidCredentialsError from exc

    async def id_token(
        self, token: str, client_id: str, nonce: str, access_token: str, principal: Principal
    ) -> int:
        claims = await asyncio.to_thread(self._decode, token, client_id, False)
        if not hmac.compare_digest(self._text(claims, "nonce").encode(), nonce.encode()):
            raise InvalidCredentialsError
        if claims["sub"] != principal.subject:
            raise InvalidCredentialsError
        audiences = claims["aud"]
        if (isinstance(audiences, list) and len(audiences) > 1) or "azp" in claims:
            if claims.get("azp") != client_id:
                raise InvalidCredentialsError
        if "at_hash" in claims:
            expected = (
                base64.urlsafe_b64encode(hashlib.sha256(access_token.encode("ascii")).digest()[:16])
                .rstrip(b"=")
                .decode("ascii")
            )
            if not hmac.compare_digest(self._text(claims, "at_hash").encode(), expected.encode()):
                raise InvalidCredentialsError
        return int(claims["exp"])
