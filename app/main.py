"""Application composition. Identity is the default; legacy mode is local/test-only."""

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import IdentitySettings, settings
from app.contexts.access.contracts import AccessDeniedError
from app.contexts.links.contracts import InvalidLinkError, LinkConflictError, LinkNotFoundError
from app.core.exceptions import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import get_logger, setup_logging
from app.core.rate_limiter import setup_rate_limiter
from app.core.redis import close_redis, get_redis
from app.core.request_id import RequestIDMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.platform.access import AccessRuntime

START_TIME = time.time()
health_router = APIRouter()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    logger = get_logger(__name__)
    production = settings.environment.lower() in {"production", "prod"}
    settings.validate_runtime_profile(app.state.auth_mode)
    if app.state.auth_mode == "identity":
        config = app.state.identity_config
        config.validate_deployment(production=production)
        if app.state.access is None:
            app.state.access = AccessRuntime.build(config)
    elif production:
        raise RuntimeError("Legacy authentication is forbidden in production")

    from app.core.schema import verify_schema
    from app.db import get_engine, get_session_factory

    async with get_session_factory()() as session:
        await session.execute(text("SELECT 1"))
    await verify_schema(get_engine())
    try:
        redis = await get_redis()
        await redis.ping()
    except Exception:
        if app.state.auth_mode == "identity":
            raise RuntimeError("Identity browser sessions and DPoP require Redis") from None
        logger.warning("Redis unavailable in local legacy profile")
    try:
        yield
    finally:
        from app.core.arq_pool import close_arq_pool

        await close_arq_pool()
        await close_redis()
        await get_engine().dispose()


async def access_denied(request: Request, exc: Exception) -> JSONResponse:
    permission = str(exc)
    headers = {"Cache-Control": "no-store"}
    if permission in {"read:links", "create:links", "update:links", "delete:links"}:
        scheme = (
            "DPoP"
            if request.headers.get("authorization", "").lower().startswith("dpop ")
            else "Bearer"
        )
        headers["WWW-Authenticate"] = f'{scheme} error="insufficient_scope", scope="{permission}"'
    return JSONResponse({"detail": "access_denied"}, status_code=403, headers=headers)


async def link_error(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, InvalidLinkError):
        return JSONResponse(
            {"detail": "invalid_link"}, status_code=422, headers={"Cache-Control": "no-store"}
        )
    conflict = isinstance(exc, LinkConflictError)
    return JSONResponse(
        {"detail": "short_code_unavailable" if conflict else "link_not_found"},
        status_code=409 if conflict else 404,
        headers={"Cache-Control": "no-store"},
    )


def create_app(
    *, auth_mode: Literal["identity", "legacy"] | None = None, access: AccessRuntime | None = None
) -> FastAPI:
    mode = auth_mode or settings.auth_mode
    production = settings.environment.lower() in {"production", "prod"}
    application = FastAPI(
        title="Plazia Links API",
        version="0.1.0",
        description="Organization-scoped link management. Identity-backed credentials required.",
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
        lifespan=lifespan,
        license_info={"name": "MIT"},
    )
    application.state.auth_mode = mode
    application.state.identity_config = access.config if access else IdentitySettings()
    application.state.access = access
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.add_exception_handler(AccessDeniedError, access_denied)
    application.add_exception_handler(LinkNotFoundError, link_error)
    application.add_exception_handler(LinkConflictError, link_error)
    application.add_exception_handler(InvalidLinkError, link_error)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=mode == "legacy",
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "DPoP"],
    )
    application.add_middleware(RequestIDMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    application.mount("/static", StaticFiles(directory=static_dir), name="static")
    if settings.rate_limit_enabled:
        setup_rate_limiter(
            application,
            redirect_requests=settings.rate_limit_redirect,
            redirect_window=settings.rate_limit_window,
            api_requests=settings.rate_limit_api,
            api_window=settings.rate_limit_window,
            auth_requests=settings.rate_limit_auth,
            auth_window=settings.rate_limit_window,
            tracking_requests=settings.rate_limit_tracking,
            tracking_window=settings.rate_limit_window,
        )
    if mode == "identity":
        from app.api.managed_links import router as links_router
        from app.routes.identity import router as browser_router

        application.include_router(links_router)
        application.include_router(browser_router)
    else:
        from app.api.email_tracking import router as tracking_router
        from app.api.router import api_router
        from app.core.csrf import CSRFMiddleware
        from app.routes.auth_routes import router as auth_router
        from app.routes.dashboard import router as dashboard_router

        application.add_middleware(CSRFMiddleware)
        application.include_router(auth_router)
        application.include_router(dashboard_router)
        application.include_router(api_router, prefix="/api/v1")
        application.include_router(tracking_router)
    application.include_router(health_router)
    from app.api.redirect import router as redirect_router

    application.include_router(redirect_router)
    if mode == "identity":
        from fastapi.openapi.utils import get_openapi

        schema = get_openapi(
            title=application.title,
            version=application.version,
            routes=application.routes,
            description=application.description,
        )
        config = application.state.identity_config
        scopes = {
            f"{action}:links": f"{action.capitalize()} links in the bound organization"
            for action in ("read", "create", "update", "delete")
        }
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["IdentityAccess"] = {
            "type": "oauth2",
            "description": (
                "Identity RS256 RFC 9068 access tokens. Unbound tokens use Bearer; "
                "cnf.jkt tokens require Authorization: DPoP and a fresh DPoP proof. "
                "The API never accepts browser session cookies."
            ),
            "flows": {
                "authorizationCode": {
                    "authorizationUrl": config.authorization_endpoint,
                    "tokenUrl": config.token_endpoint,
                    "scopes": scopes,
                },
                "clientCredentials": {"tokenUrl": config.token_endpoint, "scopes": scopes},
            },
        }
        application.openapi_schema = schema
    return application


@health_router.get("/health")
async def health(request: Request) -> JSONResponse:
    db_ok = "unknown"
    redis_ok = "unknown"

    try:
        from app.db import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        db_ok = "ok"
    except Exception:
        db_ok = "error"

    try:
        redis = await get_redis()
        await redis.ping()
        redis_ok = "ok"
    except Exception:
        redis_ok = "error"

    ready = db_ok == "ok" and (request.app.state.auth_mode != "identity" or redis_ok == "ok")
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "error",
            "database": db_ok,
            "redis": redis_ok,
            "version": "0.1.0",
            "uptime_seconds": int(time.time() - START_TIME),
        },
    )


@health_router.get("/health/live", include_in_schema=False)
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


app = create_app()

if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)
