"""Map shared verified OAuth claims to Links-owned principals."""

from typing import cast

from plazia_authlib.authn.contracts import SharedIdentityRejectedError
from plazia_authlib.authn.verifier import DiscoveryBackedSharedIdentityVerifier
from shared_http import HttpxTextClient
from shared_identity import MachineId, OrganizationId, UserId

from app.contexts.access.domain.principal import (
    AccessUnavailableError,
    InvalidCredentialsError,
    Principal,
)


class IdentityTokenVerifier:
    def __init__(self, issuer: str, audience: str) -> None:
        self.issuer = issuer
        self.audience = audience
        self._http_client = HttpxTextClient(follow_redirects=False)
        self._verifier = DiscoveryBackedSharedIdentityVerifier(
            http_client=self._http_client,
            openid_configuration_urls=(issuer.rstrip("/") + "/.well-known/openid-configuration",),
            human_audience=audience,
            timeout_seconds=5,
        )

    async def close(self) -> None:
        await self._http_client.aclose()

    async def access_token(self, token: str) -> Principal:
        try:
            claims = await self._verifier.verify_oauth_access_token(
                token=token, audience=self.audience
            )
            subject = cast(str, claims["sub"])
            canonical = MachineId(subject) if subject.startswith("mch_") else UserId(subject)
            confirmation = cast(dict[str, str], claims.get("cnf", {}))
            return Principal(
                self.issuer,
                str(canonical),
                cast(str, claims["client_id"]),
                OrganizationId(claims.get("org")),
                frozenset(cast(str, claims.get("scope", "")).split()),
                cast(int, claims["exp"]),
                cast(str, claims["jti"]),
                confirmation.get("jkt"),
            )
        except SharedIdentityRejectedError as error:
            if error.code == "shared_identity_document_unavailable":
                raise AccessUnavailableError from error
            raise InvalidCredentialsError from error
        except (TypeError, ValueError) as error:
            raise InvalidCredentialsError from error

    async def id_token(
        self, token: str, client_id: str, nonce: str, access_token: str, principal: Principal
    ) -> int:
        try:
            claims = await self._verifier.verify_id_token(
                token=token,
                client_id=client_id,
                nonce=nonce,
                access_token=access_token,
                subject=principal.subject,
            )
            return cast(int, claims["exp"])
        except SharedIdentityRejectedError as error:
            if error.code == "shared_identity_document_unavailable":
                raise AccessUnavailableError from error
            raise InvalidCredentialsError from error
