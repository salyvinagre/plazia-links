"""Links replay-store binding for the shared RFC 9449 proof verifier."""

from datetime import timedelta

from plazia_authlib.authn.dpop import DpopProofVerifier, DpopVerificationError

from app.contexts.access.application.ports.session import EphemeralStore
from app.contexts.access.domain.principal import InvalidCredentialsError


class DpopReplayVerifier:
    def __init__(self, store: EphemeralStore, *, allow_insecure_loopback: bool = False) -> None:
        self._store = store
        self._proofs = DpopProofVerifier(
            allow_insecure_loopback=allow_insecure_loopback, window=timedelta(seconds=120)
        )

    async def verify(self, proof: str, access_token: str, jkt: str, method: str, uri: str) -> None:
        try:
            verified = self._proofs.verify(
                proof, method=method, uri=uri, access_token=access_token, expected_jkt=jkt
            )
        except DpopVerificationError as error:
            raise InvalidCredentialsError from error
        if not await self._store.consume_once(
            f"{verified.key_thumbprint}:{verified.proof_id}", 130
        ):
            raise InvalidCredentialsError
