import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.email_tracking import router as email_tracking_router
from app.api.router import api_router, redirect_router
from app.config import settings
from app.core.csrf import CSRFMiddleware
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
from app.routes.auth_routes import router as auth_router
from app.routes.dashboard import router as dashboard_router

START_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    logger = get_logger(__name__)

    try:
        from app.db import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        logger.info("Database connection verified")
        from app.core.schema import verify_schema
        from app.db import get_engine

        await verify_schema(get_engine())
    except Exception as e:
        logger.critical("Database startup verification failed", extra={"error": str(e)})
        raise

    try:
        redis = await get_redis()
        await redis.ping()
        logger.info("Redis connection verified")
    except Exception:
        logger.warning("Redis unreachable on startup — some features degraded")

    is_prod = os.getenv("ENVIRONMENT", "").lower() in ("production", "prod")
    default_warnings = []
    if settings.secret_key == "change-me-in-production":
        default_warnings.append("SECRET_KEY")
    if settings.jwt_secret == "change-me-in-production":
        default_warnings.append("JWT_SECRET")
    if default_warnings:
        msg = (
            f"Default secrets in use: {', '.join(default_warnings)}. "
            "Set strong values in production."
        )
        if is_prod:
            logger.critical(msg)
            raise RuntimeError(msg)
        logger.warning(msg)

    yield
    from app.core.arq_pool import close_arq_pool
    from app.db import get_engine

    await close_arq_pool()
    await close_redis()
    await get_engine().dispose()


app = FastAPI(
    title="Zly API",
    description=(
        "Open-source URL shortener and marketing platform. "
        "Shorten URLs, track clicks, manage campaigns, and more."
    ),
    version="0.1.0",
    docs_url=None if os.getenv("ENVIRONMENT", "").lower() in ("production", "prod") else "/docs",
    redoc_url=None if os.getenv("ENVIRONMENT", "").lower() in ("production", "prod") else "/redoc",
    contact={
        "name": "PythonPlumber",
        "url": "https://senuka.me",
        "email": "pythonplumber@senuka.me",
    },
    license_info={
        "name": "MIT",
        "url": "https://github.com/pythonplumber/zly/blob/main/LICENSE",
    },
    lifespan=lifespan,
    openapi_tags=[
        {"name": "auth", "description": "Authentication and user registration"},
        {"name": "links", "description": "Create, update, delete, and manage short links"},
        {"name": "workspaces", "description": "Workspace management"},
        {"name": "tags", "description": "Organize links with tags"},
        {"name": "webhooks", "description": "Webhook integrations for events"},
        {"name": "api-keys", "description": "API key management for programmatic access"},
        {"name": "analytics", "description": "Click analytics and statistics"},
        {"name": "domains", "description": "Custom domain management"},
        {"name": "invites", "description": "Workspace member invites"},
        {"name": "bio", "description": "Link-in-bio pages"},
        {"name": "ab-testing", "description": "A/B testing variants for links"},
        {"name": "bulk", "description": "Bulk import and export operations"},
        {"name": "email-campaigns", "description": "Email campaign management"},
        {"name": "email-tracking", "description": "Email open and click tracking"},
        {"name": "audit", "description": "Audit log access"},
        {"name": "admin", "description": "Superuser admin operations"},
        {"name": "oauth", "description": "OAuth/SSO login with Google and GitHub"},
        {"name": "users", "description": "User profile and settings"},
        {"name": "sessions", "description": "Session management and revocation"},
    ],
)

sentry_dsn = os.getenv("SENTRY_DSN", "")
if sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.1)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)

# Static files — serves app/static/* at /static/*
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

if settings.rate_limit_enabled:
    setup_rate_limiter(
        app,
        redirect_requests=settings.rate_limit_redirect,
        redirect_window=settings.rate_limit_window,
        api_requests=settings.rate_limit_api,
        api_window=settings.rate_limit_window,
        auth_requests=settings.rate_limit_auth,
        auth_window=settings.rate_limit_window,
        tracking_requests=settings.rate_limit_tracking,
        tracking_window=settings.rate_limit_window,
    )

app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(api_router, prefix="/api/v1")
app.include_router(email_tracking_router)


@app.get("/health")
async def health() -> JSONResponse:
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

    return JSONResponse(
        status_code=200 if db_ok == "ok" else 503,
        content={
            "status": "ok" if db_ok == "ok" else "error",
            "database": db_ok,
            "redis": redis_ok,
            "version": "0.1.0",
            "uptime_seconds": int(time.time() - START_TIME),
        },
    )


@app.get("/health/live", include_in_schema=False)
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(redirect_router)
