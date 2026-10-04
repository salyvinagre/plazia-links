"""FastAPI composition: one production profile, one PostgreSQL schema authority."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from shared_http import PageTokenError
from shared_http.fastapi import ApiErrorResponse, ApiResponse, install_linked
from shared_http.fastapi.telemetry import FastApiHttpTelemetry

from app.contexts.access.adapters.authorization import OpenFgaOrganizationAuthority
from app.contexts.access.contracts import AccessDeniedError, AccessUnavailableError
from app.contexts.links.contracts import (
    LinkConflictError,
    LinkNotFoundError,
    PixelConflictError,
    PixelNotFoundError,
    StatisticsUnavailableError,
)
from app.contexts.links.domain.link import IdempotencyConflictError, LinkDisabledError
from app.interfaces.api.links import router as api_router
from app.interfaces.api.pixels import router as pixels_api_router
from app.interfaces.browser import router as browser_router
from app.interfaces.middleware.rate_limiter import setup_rate_limiter
from app.interfaces.middleware.request_id import RequestIDMiddleware
from app.interfaces.middleware.security_headers import SecurityHeadersMiddleware
from app.interfaces.public import router as public_router
from app.platform.access import AccessRuntime
from app.platform.composition import Container
from app.platform.database import PostgresDatabase, PostgresUowFactory
from app.platform.logging import get_logger, setup_logging
from app.platform.persistence.schema import SchemaAuthority
from app.platform.redis import close_redis, get_redis
from app.platform.settings import IdentitySettings, Settings
from app.platform.telemetry import build_telemetry


class HealthResponse(ApiResponse):
    status: Literal["ok"] = "ok"


async def error_response(request: Request, exc: Exception) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if isinstance(exc, HTTPException):
        status = exc.status_code
        code = exc.detail if isinstance(exc.detail, str) else "request_failed"
        headers |= dict(exc.headers or {})
        if request.headers.get("HX-Request") == "true" and 300 <= status < 400:
            return JSONResponse(
                {}, headers={"Cache-Control": "no-store", "HX-Redirect": headers["Location"]}
            )
    elif isinstance(exc, AccessDeniedError):
        status, code = 403, "access_denied"
    elif isinstance(exc, AccessUnavailableError):
        status, code = 503, "authority_unavailable"
    elif isinstance(exc, StatisticsUnavailableError):
        status, code = 503, "statistics_unavailable"
    elif isinstance(exc, LinkNotFoundError):
        status, code = 404, "link_not_found"
    elif isinstance(exc, PixelNotFoundError):
        status, code = 404, "pixel_not_found"
    elif isinstance(exc, PixelConflictError):
        status, code = 409, "pixel_allocation_conflict"
    elif isinstance(exc, PageTokenError):
        status, code = 400, "invalid_page_token"
    elif isinstance(exc, LinkDisabledError):
        status, code = 410, "link_disabled"
    elif isinstance(exc, IdempotencyConflictError):
        status, code = 409, "idempotency_conflict"
    elif isinstance(exc, LinkConflictError):
        status, code = 409, "short_code_unavailable"
    elif isinstance(exc, RequestValidationError) and any(
        error["loc"][:2] == ("header", "Idempotency-Key") for error in exc.errors()
    ):
        status, code = 400, "invalid_idempotency_key"
    elif isinstance(exc, (ValueError, RequestValidationError)):
        status, code = 422, "invalid_request"
    else:
        status, code = 500, "internal_error"
        get_logger(__name__).error(
            "Request failed",
            extra={
                "request_id": getattr(request.state, "request_id", ""),
                "trace_id": getattr(getattr(request.state, "trace", None), "trace_id", None),
                "error_type": type(exc).__name__,
            },
        )
    messages = {
        400: "The request context is invalid.",
        401: "Authentication is required.",
        403: "This action is not permitted.",
        404: "The resource is unavailable.",
        409: "The request conflicts with existing state.",
        410: "The link is disabled.",
        422: "The request does not meet the contract.",
        429: "Try again later.",
        503: "A required service is unavailable.",
    }
    return JSONResponse(
        ApiErrorResponse(
            code=code, message=messages.get(status, "The request could not be completed.")
        ).model_dump(),
        status_code=status,
        headers=headers,
    )


def create_app(
    *,
    access: AccessRuntime | None = None,
    database: Any = None,
    uow_factory: Any = None,
    authority: Any = None,
    config: Settings | None = None,
) -> FastAPI:
    config = config or Settings()
    identity = access.config if access else IdentitySettings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        setup_logging()
        config.validate_runtime()
        identity.validate_deployment(production=config.environment in {"production", "prod"})
        async with AsyncExitStack() as cleanup:
            application.state.telemetry = build_telemetry(config, "api")
            cleanup.callback(application.state.telemetry.shutdown)
            cleanup.callback(application.state.telemetry.force_flush)
            if application.state.database is None:
                cleanup.push_async_callback(close_redis)
                SchemaAuthority(config.database_url.get_secret_value()).check(runtime="app")
                application.state.database = PostgresDatabase(
                    config.database_url.get_secret_value(),
                    pooled=config.deployment_mode == "container",
                )
                cleanup.push_async_callback(application.state.database.close)
                application.state.authority = OpenFgaOrganizationAuthority(
                    config.openfga_url,
                    config.openfga_store_id.get_secret_value(),
                    config.openfga_model_id.get_secret_value(),
                )
                cleanup.push_async_callback(application.state.authority.close)
                application.state.commands, application.state.queries = Container.buses(
                    application.state.database,
                    PostgresUowFactory(application.state.database),
                    application.state.authority,
                    application.state.telemetry,
                )
                store = await get_redis()
                await store.ping()
                application.state.access = AccessRuntime.build(identity)
                cleanup.push_async_callback(application.state.access.tokens.close)
            yield

    production = config.environment in {"production", "prod"}
    application = FastAPI(
        title="Plazia Links API",
        version="0.2.0",
        description="Organization-owned link pools and activation.",
        servers=[{"url": "/", "description": "Current deployment"}],
        openapi_tags=[
            {"name": "links", "description": "Manage organization links and pools."},
            {
                "name": "pixels",
                "description": "Manage email delivery pixels and image request statistics.",
            },
        ],
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    application.state.database = database
    application.state.authority = authority
    application.state.access = access
    application.state.identity_config = identity
    if database is not None:
        application.state.commands, application.state.queries = Container.buses(
            database, uow_factory, authority
        )
    for kind in (
        HTTPException,
        RequestValidationError,
        AccessDeniedError,
        AccessUnavailableError,
        StatisticsUnavailableError,
        LinkNotFoundError,
        PixelNotFoundError,
        PixelConflictError,
        LinkDisabledError,
        LinkConflictError,
        IdempotencyConflictError,
        ValueError,
        Exception,
    ):
        application.add_exception_handler(kind, error_response)
    if config.rate_limit_enabled:
        setup_rate_limiter(application, frozenset(map(str, config.trusted_proxy_ips)))
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RequestIDMiddleware)
    FastApiHttpTelemetry(instrumentation_scope="links.http").install(application)
    application.mount(
        "/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static"
    )

    @application.get("/health", include_in_schema=False)
    async def health() -> HealthResponse:
        """Check that the process is running."""
        return HealthResponse()

    @application.get("/", include_in_schema=False)
    async def home() -> Any:
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/dashboard/links", status_code=303)

    application.include_router(api_router)
    application.include_router(pixels_api_router)
    application.include_router(browser_router)
    application.include_router(public_router)
    install_linked(application)
    return application


app = create_app()
