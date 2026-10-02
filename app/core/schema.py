"""Read-only schema compatibility check; migrations run before application startup."""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine


def expected_schema_heads() -> set[str]:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    heads = set(ScriptDirectory.from_config(config).get_heads())
    if len(heads) != 1:
        raise RuntimeError("Expected exactly one Alembic head; repair migration history first")
    return heads


def current_schema_heads(connection: Connection) -> set[str]:
    return set(MigrationContext.configure(connection).get_current_heads())


async def verify_schema(engine: AsyncEngine) -> None:
    expected = expected_schema_heads()
    async with engine.connect() as connection:
        actual = await connection.run_sync(current_schema_heads)
    if actual != expected:
        raise RuntimeError(
            "Database schema is not current; run alembic upgrade head before startup"
        )
