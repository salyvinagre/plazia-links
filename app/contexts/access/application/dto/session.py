"""Transport-neutral session state."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LoginAttemptDto:
    verifier: str
    nonce: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class TokenPairDto:
    access_token: str
    id_token: str
