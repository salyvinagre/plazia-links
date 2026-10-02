from redis.asyncio import ConnectionPool, Redis

from app.platform.settings import settings

pool: ConnectionPool | None = None


async def get_redis() -> Redis:
    global pool
    if pool is None:
        pool = ConnectionPool.from_url(
            settings.redis_url.get_secret_value(),
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return Redis(connection_pool=pool)


async def close_redis() -> None:
    global pool
    if pool:
        await pool.disconnect()
        pool = None
