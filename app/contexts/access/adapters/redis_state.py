"""Shared, expiring state; no local-memory fallback for sessions or replay checks."""

import hashlib
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.contexts.access.domain.principal import AccessUnavailableError


class RedisState:
    def __init__(self, client: Callable[[], Awaitable[Redis]]) -> None:
        self._client = client

    @staticmethod
    def _key(purpose: str, value: str) -> str:
        digest = hashlib.sha256(value.encode()).hexdigest()
        return f"plazia-links:access:{purpose}:{digest}"

    async def put(self, purpose: str, key: str, value: str, ttl: int) -> None:
        try:
            redis = await self._client()
            await redis.set(self._key(purpose, key), value, ex=max(1, ttl))
        except (RedisError, OSError) as exc:
            raise AccessUnavailableError from exc

    async def get(self, purpose: str, key: str) -> str | None:
        try:
            redis = await self._client()
            value = await redis.get(self._key(purpose, key))
            return str(value) if value is not None else None
        except (RedisError, OSError) as exc:
            raise AccessUnavailableError from exc

    async def take(self, purpose: str, key: str) -> str | None:
        try:
            redis = await self._client()
            value = await redis.getdel(self._key(purpose, key))
            return str(value) if value is not None else None
        except (RedisError, OSError) as exc:
            raise AccessUnavailableError from exc

    async def remove(self, purpose: str, key: str) -> None:
        try:
            redis = await self._client()
            await redis.delete(self._key(purpose, key))
        except (RedisError, OSError) as exc:
            raise AccessUnavailableError from exc

    async def consume_once(self, key: str, ttl: int) -> bool:
        try:
            redis = await self._client()
            return bool(await redis.set(self._key("dpop", key), "1", nx=True, ex=ttl))
        except (RedisError, OSError) as exc:
            raise AccessUnavailableError from exc
