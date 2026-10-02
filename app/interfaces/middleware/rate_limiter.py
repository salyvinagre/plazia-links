"""Atomic Redis admission; forwarded identity requires an explicit proxy allowlist."""

import hashlib
from ipaddress import ip_address
from typing import Any, cast

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from shared_http.fastapi import ApiErrorResponse
from starlette.middleware.base import RequestResponseEndpoint

from app.platform.redis import get_redis

_SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {n, redis.call('TTL', KEYS[1])}
"""


def setup_rate_limiter(app: FastAPI, trusted_proxy_ips: frozenset[str] = frozenset()) -> None:
    @app.middleware("http")
    async def admission(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith(("/static", "/health")):
            return await call_next(request)
        category = (
            "login"
            if request.url.path in {"/login", "/auth/callback"}
            else "public"
            if request.url.path.endswith("/subscriptions")
            else "request"
        )
        limit = 10 if category == "login" else 20 if category == "public" else 120
        peer = request.client.host if request.client else "unknown"
        if peer in trusted_proxy_ips:
            forwarded = request.headers.getlist("X-Forwarded-For")
            if len(forwarded) == 1 and len(forwarded[0]) <= 2048:
                try:
                    # The allowlisted proxy must append its observed peer, or overwrite the header.
                    peer = str(ip_address(forwarded[0].rsplit(",", 1)[-1].strip()))
                except ValueError:
                    pass
        key = "plazia-links:rate:" + category + ":" + hashlib.sha256(peer.encode()).hexdigest()
        try:
            client = await get_redis()
            count, ttl = await cast(Any, client).eval(_SCRIPT, 1, key, "60")
        except RedisError, OSError:
            return JSONResponse(
                ApiErrorResponse(
                    code="admission_unavailable", message="Try again later."
                ).model_dump(),
                status_code=503,
            )
        if count > limit:
            return JSONResponse(
                ApiErrorResponse(code="rate_limited", message="Try again later.").model_dump(),
                status_code=429,
                headers={"Retry-After": str(max(1, ttl))},
            )
        return await call_next(request)
