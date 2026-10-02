"""Strict primitive session records; canonical IDs are parsed at this boundary."""

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from shared_identity.canonical_ids import OrganizationId

from app.contexts.access.application.dto.session import LoginAttemptDto
from app.contexts.access.application.ports.session import EphemeralStore
from app.contexts.access.domain.principal import BrowserSession, InvalidCredentialsError, Principal


class SessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str
    subject: str
    client_id: str
    organization_id: str
    scopes: frozenset[str]
    token_expires_at: int
    token_id: str
    confirmation_jkt: str | None
    csrf_token: str
    expires_at: int


class StoredBrowserState:
    def __init__(self, store: EphemeralStore) -> None:
        self._store = store
        self._attempts = TypeAdapter(LoginAttemptDto)

    async def put_attempt(self, key: str, attempt: LoginAttemptDto, ttl: int) -> None:
        await self._store.put("login", key, self._attempts.dump_json(attempt).decode(), ttl)

    async def take_attempt(self, key: str) -> LoginAttemptDto | None:
        raw = await self._store.take("login", key)
        if raw is None:
            return None
        try:
            return self._attempts.validate_json(raw)
        except ValidationError as exc:
            raise InvalidCredentialsError from exc

    async def put_session(self, handle: str, session: BrowserSession, ttl: int) -> None:
        actor = session.principal
        record = SessionRecord(
            issuer=actor.issuer,
            subject=actor.subject,
            client_id=actor.client_id,
            organization_id=str(actor.organization_id),
            scopes=actor.scopes,
            token_expires_at=actor.expires_at,
            token_id=actor.token_id,
            confirmation_jkt=actor.confirmation_jkt,
            csrf_token=session.csrf_token,
            expires_at=session.expires_at,
        )
        await self._store.put("session", handle, record.model_dump_json(), ttl)

    async def get_session(self, handle: str) -> BrowserSession | None:
        raw = await self._store.get("session", handle)
        if raw is None:
            return None
        try:
            record = SessionRecord.model_validate_json(raw)
            actor = Principal(
                record.issuer,
                record.subject,
                record.client_id,
                OrganizationId(record.organization_id),
                record.scopes,
                record.token_expires_at,
                record.token_id,
                record.confirmation_jkt,
            )
            return BrowserSession(actor, record.csrf_token, record.expires_at)
        except (ValidationError, ValueError) as exc:
            raise InvalidCredentialsError from exc

    async def remove_session(self, handle: str) -> None:
        await self._store.remove("session", handle)
