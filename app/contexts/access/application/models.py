"""Transport-neutral state exchanged through access application ports."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LoginAttempt:
    verifier: str
    nonce: str
    expires_at: int


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    id_token: str


@dataclass(frozen=True)
class WorkspaceView:
    id: str
    name: str


@dataclass(frozen=True)
class WorkspaceBinding:
    workspace: WorkspaceView
    active: bool
