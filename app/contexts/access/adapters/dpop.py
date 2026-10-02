"""Bounded RFC 9449 resource-server proof verification; replay state is shared."""

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import jwt

from app.contexts.access.application.ports.session import EphemeralStore
from app.contexts.access.domain.principal import InvalidCredentialsError


class DPoPVerifier:
    WINDOW = 120
    LEEWAY = 5

    def __init__(self, store: EphemeralStore) -> None:
        self._store = store

    @staticmethod
    def digest(value: bytes) -> str:
        return base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=").decode()

    @staticmethod
    def canonical_uri(uri: str) -> str:
        parsed = urlsplit(uri)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username:
            raise InvalidCredentialsError
        port = parsed.port
        default = 443 if parsed.scheme == "https" else 80
        host = parsed.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        authority = host if port in (None, default) else f"{host}:{port}"
        return urlunsplit((parsed.scheme.lower(), authority, parsed.path or "/", "", ""))

    @classmethod
    def thumbprint(cls, jwk: dict[str, Any]) -> str:
        if any(key in jwk for key in ("d", "p", "q", "dp", "dq", "qi", "oth", "k")):
            raise InvalidCredentialsError
        members: tuple[str, ...]
        if jwk.get("kty") == "EC" and jwk.get("crv") == "P-256":
            members = ("crv", "kty", "x", "y")
        elif jwk.get("kty") == "RSA":
            members = ("e", "kty", "n")
        else:
            raise InvalidCredentialsError
        if any(not isinstance(jwk.get(k), str) or not jwk[k] for k in members):
            raise InvalidCredentialsError
        canonical = json.dumps({k: jwk[k] for k in members}, sort_keys=True, separators=(",", ":"))
        return cls.digest(canonical.encode())

    async def verify(self, proof: str, access_token: str, jkt: str, method: str, uri: str) -> None:
        try:
            if len(proof) > 16384 or proof.count(".") != 2:
                raise InvalidCredentialsError
            header = jwt.get_unverified_header(proof)
            if header.get("typ") != "dpop+jwt" or header.get("crit"):
                raise InvalidCredentialsError
            algorithm = header.get("alg")
            key_data = header.get("jwk")
            if algorithm not in {"RS256", "ES256"} or not isinstance(key_data, dict):
                raise InvalidCredentialsError
            if (algorithm == "RS256") != (key_data.get("kty") == "RSA"):
                raise InvalidCredentialsError
            if not hmac.compare_digest(self.thumbprint(key_data), jkt):
                raise InvalidCredentialsError
            key = jwt.PyJWK.from_dict(key_data, algorithm=algorithm).key
            claims = jwt.decode(
                proof,
                key,
                algorithms=[algorithm],
                leeway=self.LEEWAY,
                options={"require": ["jti", "iat", "htm", "htu", "ath"], "verify_aud": False},
            )
            if type(claims["iat"]) is not int:
                raise InvalidCredentialsError
            if not time.time() - self.WINDOW <= claims["iat"] <= time.time() + self.LEEWAY:
                raise InvalidCredentialsError
            if claims["htm"] != method or not isinstance(claims["htu"], str):
                raise InvalidCredentialsError
            if self.canonical_uri(claims["htu"]) != self.canonical_uri(uri):
                raise InvalidCredentialsError
            if not isinstance(claims["ath"], str) or not hmac.compare_digest(
                claims["ath"], self.digest(access_token.encode("ascii"))
            ):
                raise InvalidCredentialsError
            jti = claims["jti"]
            if not isinstance(jti, str) or not 1 <= len(jti) <= 200:
                raise InvalidCredentialsError
            if not await self._store.consume_once(f"{jkt}:{jti}", self.WINDOW + 2 * self.LEEWAY):
                raise InvalidCredentialsError
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise InvalidCredentialsError from exc
