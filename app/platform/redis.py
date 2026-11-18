from os import getenv
from urllib.parse import parse_qsl, urlencode, urlsplit

from redis.asyncio import ConnectionPool, Redis

from app.platform.settings import Settings

pool: ConnectionPool | None = None


async def get_redis() -> Redis:
    global pool
    if pool is None:
        url = urlsplit(Settings().redis_url.get_secret_value())
        if url.scheme == "rediss" and (root := getenv("PLZ_PKI_ROOT_FILE")):
            options = dict(parse_qsl(url.query, keep_blank_values=True))
            options["ssl_ca_certs"] = root
            url = url._replace(query=urlencode(options))
        pool = ConnectionPool.from_url(
            url.geturl(),
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
