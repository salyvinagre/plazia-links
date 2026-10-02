"""Database connection ownership is a runtime concern, not a domain decision."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings


class DatabaseRuntime:
    @staticmethod
    def create_engine(config: Settings) -> AsyncEngine:
        if config.deployment_mode == "serverless":
            # Do not retain connections across invocation/event-loop lifecycles. Use a direct
            # TLS PostgreSQL endpoint; transaction-pooler-specific support is not assumed.
            return create_async_engine(config.database_url, echo=False, poolclass=NullPool)
        return create_async_engine(config.database_url, echo=False, pool_pre_ping=True)
