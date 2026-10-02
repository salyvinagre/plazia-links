"""Serialization belongs at the storage boundary, not in the browser use case."""

from pydantic import TypeAdapter, ValidationError

from app.contexts.access.application.models import LoginAttempt
from app.contexts.access.application.ports import EphemeralStore
from app.contexts.access.domain.principal import BrowserSession, InvalidCredentialsError


class StoredBrowserState:
    def __init__(self, store: EphemeralStore) -> None:
        self._store = store
        self._attempts = TypeAdapter(LoginAttempt)
        self._sessions = TypeAdapter(BrowserSession)

    async def put_attempt(self, key: str, attempt: LoginAttempt, ttl: int) -> None:
        await self._store.put("login", key, self._attempts.dump_json(attempt).decode(), ttl)

    async def take_attempt(self, key: str) -> LoginAttempt | None:
        raw = await self._store.take("login", key)
        if raw is None:
            return None
        try:
            return self._attempts.validate_json(raw)
        except ValidationError as exc:
            raise InvalidCredentialsError from exc

    async def put_session(self, handle: str, session: BrowserSession, ttl: int) -> None:
        await self._store.put("session", handle, self._sessions.dump_json(session).decode(), ttl)

    async def get_session(self, handle: str) -> BrowserSession | None:
        raw = await self._store.get("session", handle)
        if raw is None:
            return None
        try:
            return self._sessions.validate_json(raw)
        except ValidationError as exc:
            raise InvalidCredentialsError from exc

    async def remove_session(self, handle: str) -> None:
        await self._store.remove("session", handle)
