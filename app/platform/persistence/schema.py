"""Read-only admission and verification for the Flyway-owned Links schema."""

from __future__ import annotations

import re
import zlib
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import psycopg
from psycopg import Connection

_MIGRATION_SCHEMA: Final = "links_migrations"
_OWNED_SCHEMAS: Final = ("access", "links", "platform")
_ROLE_PATTERN: Final = re.compile(r"links_[a-z][a-z0-9_]{0,24}")
_SQL: Final = (Path(__file__).parent / "sql/migrations/V1__link_pools.sql").read_text()
# Flyway CRC32 ignores line endings/BOM and is stored as a signed Java int.
_MIGRATION_CHECKSUM: Final = zlib.crc32("".join(_SQL.lstrip("\ufeff").splitlines()).encode())
_EXPECTED_HISTORY: Final = (
    (
        "1",
        "V1__link_pools.sql",
        True,
        "SQL",
        _MIGRATION_CHECKSUM if _MIGRATION_CHECKSUM < 2**31 else _MIGRATION_CHECKSUM - 2**32,
    ),
)
_FUNCTION_SECURITY: Final = {
    (schema, name): (
        body.strip(),
        "SECURITY DEFINER" in header,
        ("search_path=" + re.findall(r"SET search_path = ([^\n]+)", header)[0],),
    )
    for schema, name, header, body in re.findall(
        r"CREATE FUNCTION (\w+)\.(\w+)(.*?)AS \$\$(.*?)\$\$;", _SQL, re.DOTALL
    )
}
_EXPECTED_TABLES: Final = frozenset(
    {
        "access.organizations",
        "links.links",
        "links.pools",
        "links.subscriptions",
        "platform.activation_emails",
        "platform.audit_events",
        "platform.command_receipts",
        "links_migrations.flyway_schema_history",
    }
)
_RLS_TABLES: Final = frozenset(
    {
        "access.organizations",
        "links.links",
        "links.pools",
        "links.subscriptions",
        "platform.activation_emails",
        "platform.audit_events",
        "platform.command_receipts",
    }
)


class SchemaError(RuntimeError):
    """Raised when the selected database is not a fresh or current Links target."""


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    revision: str
    tables: tuple[str, ...]
    functions: tuple[tuple[str, str], ...]


class SchemaAuthority:
    """Check Links storage without creating schemas or running migrations."""

    def __init__(
        self,
        database_url: str,
        *,
        app_role: str = "links_app",
        worker_role: str = "links_worker",
    ) -> None:
        if not database_url.strip():
            raise ValueError("schema database URL is required")
        if not database_url.strip().startswith(("postgresql://", "postgres://")):
            raise ValueError("Schema verification requires a PostgreSQL URL")
        self.database_url = database_url.strip()
        self.app_role = self._role(app_role)
        self.worker_role = self._role(worker_role)
        if self.app_role == self.worker_role:
            raise ValueError("application and worker database roles must be distinct")

    def prepare(self) -> None:
        """Admit only an empty target or an exact Flyway V1 database."""

        with self._connection() as connection:
            self._require_runtime_roles(connection)
            history = self._history(connection)
            if history:
                self._status(connection)
                return
            existing = self._owned_schemas(connection)
            if existing:
                raise SchemaError(
                    "unversioned Links schemas are unsupported; use a fresh Flyway target"
                )

    def finish(self) -> SchemaStatus:
        """Verify the schema and authority produced by Flyway."""

        with self._connection() as connection:
            self._require_runtime_roles(connection)
            return self._status(connection)

    def check(self, *, runtime: Literal["app", "worker"] | None = None) -> SchemaStatus:
        """Read and verify the current Flyway schema state."""

        with self._connection() as connection:
            self._require_runtime_roles(connection)
            if runtime is not None:
                row = connection.execute(
                    """SELECT current_user, EXISTS (
                    SELECT 1 FROM pg_catalog.pg_roles r
                    WHERE pg_catalog.pg_has_role(current_user, r.oid, 'MEMBER') AND (
                        r.rolsuper OR r.rolbypassrls OR
                        (r.rolname <> current_user AND r.rolname = ANY(%s)) OR r.oid IN (
                            SELECT nspowner FROM pg_catalog.pg_namespace
                            WHERE nspname = ANY(%s))))""",
                    ([self.app_role, self.worker_role], [*_OWNED_SCHEMAS, _MIGRATION_SCHEMA]),
                ).fetchone()
                expected = self.app_role if runtime == "app" else self.worker_role
                if row is None or row[0] != expected or row[1]:
                    raise SchemaError(
                        "Runtime requires its dedicated role without owner membership"
                    )
            return self._status(connection)

    @contextmanager
    def _connection(self) -> Generator[Connection[tuple[Any, ...]]]:
        try:
            with psycopg.connect(self.database_url, autocommit=True) as db:
                with db.transaction():
                    db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    yield db
        except SchemaError:
            raise
        except psycopg.Error as error:
            raise SchemaError("Links schema verification failed") from error

    def _require_runtime_roles(self, connection: Connection[tuple[Any, ...]]) -> None:
        rows = connection.execute(
            """
            SELECT rolname, rolcanlogin, rolsuper, rolbypassrls
            FROM pg_catalog.pg_roles
            WHERE rolname = ANY(%s)
            """,
            ([self.app_role, self.worker_role],),
        ).fetchall()
        roles = {row[0]: row[1:] for row in rows}
        if set(roles) != {self.app_role, self.worker_role}:
            raise SchemaError("Links application and worker roles must already exist")
        if any(
            not login or superuser or bypass_rls for login, superuser, bypass_rls in roles.values()
        ):
            raise SchemaError("Links runtime roles must be login roles without elevated bypass")

    def _status(self, connection: Connection[tuple[Any, ...]]) -> SchemaStatus:
        if self._history(connection) != _EXPECTED_HISTORY:
            raise SchemaError("Links Flyway history is missing or incompatible")
        schemas = self._owned_schemas(connection)
        if schemas != frozenset((*_OWNED_SCHEMAS, _MIGRATION_SCHEMA)):
            raise SchemaError("Links PostgreSQL schemas are incomplete")

        tables = frozenset(
            row[0]
            for row in connection.execute(
                """
                SELECT n.nspname || '.' || c.relname
                FROM pg_catalog.pg_class AS c
                JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p')
                """,
                ([*_OWNED_SCHEMAS, _MIGRATION_SCHEMA],),
            ).fetchall()
        )
        if tables != _EXPECTED_TABLES:
            raise SchemaError("Links table catalog differs from Flyway V1")

        rls = frozenset(
            row[0]
            for row in connection.execute(
                """
                SELECT n.nspname || '.' || c.relname
                FROM pg_catalog.pg_class AS c
                JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s) AND c.relrowsecurity
                """,
                ([*_OWNED_SCHEMAS],),
            ).fetchall()
        )
        if rls != _RLS_TABLES:
            raise SchemaError("Links row-level security differs from Flyway V1")

        functions = {
            (row[0], row[1]): (row[2].strip(), row[3], tuple(row[4] or ()))
            for row in connection.execute(
                """SELECT n.nspname,p.proname,p.prosrc,p.prosecdef,p.proconfig
                FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname = ANY(%s) AND p.prokind='f'""",
                (list(_OWNED_SCHEMAS),),
            ).fetchall()
        }
        if functions != _FUNCTION_SECURITY:
            raise SchemaError("Links security functions differ from the packaged migration")
        owner_drift = connection.execute(
            """SELECT EXISTS (
                SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n
                ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s) AND c.relowner <> n.nspowner
            ) OR EXISTS (
                SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n
                ON n.oid=p.pronamespace WHERE n.nspname=ANY(%s) AND p.proowner <> n.nspowner
             ) OR EXISTS (
                SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n
                ON n.oid=p.pronamespace, LATERAL pg_catalog.aclexplode(
                    coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a
                WHERE n.nspname=ANY(%s) AND a.grantee=0 AND a.privilege_type='EXECUTE'
            ) AS owner_drift""",
            (list(_OWNED_SCHEMAS), list(_OWNED_SCHEMAS), list(_OWNED_SCHEMAS)),
        ).fetchone()
        if owner_drift is None or owner_drift[0]:
            raise SchemaError("Links object ownership differs from schema authority")
        policies = {
            (row[0], row[1]): (row[2], row[3], tuple(row[4]), row[5], row[6])
            for row in connection.execute(
                """SELECT n.nspname||'.'||c.relname,p.polname,
                p.polcmd,p.polpermissive,ARRAY(SELECT CASE WHEN r=0 THEN 'public'
                    ELSE pg_catalog.pg_get_userbyid(r)::text END
                    FROM unnest(p.polroles) r ORDER BY 1),
                pg_catalog.pg_get_expr(p.polqual,p.polrelid),
                pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid)
                FROM pg_catalog.pg_policy p JOIN pg_catalog.pg_class c ON c.oid=p.polrelid
                JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=ANY(%s)""",
                (list(_OWNED_SCHEMAS),),
            ).fetchall()
        }
        if policies != self._policies():
            raise SchemaError("Links tenant policies differ from the packaged migration")
        private_access = connection.execute(
            """SELECT bool_or(CASE
                WHEN n.nspname='links' AND c.relname='subscriptions'
                    THEN has_any_column_privilege(%s,c.oid,'SELECT')
                WHEN n.nspname='platform' AND c.relname='activation_emails'
                    THEN has_any_column_privilege(%s,c.oid,'SELECT')
                WHEN n.nspname='access' AND c.relname='organizations'
                    THEN has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE')
                WHEN n.nspname='links' AND c.relname='links'
                    THEN has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE')
                ELSE false END
                OR (n.nspname='links' AND c.relname='pools'
                    AND has_table_privilege(%s,c.oid,'UPDATE,DELETE'))
                OR (n.nspname||'.'||c.relname = ANY(%s) AND (
                    has_any_column_privilege(%s,c.oid,'SELECT,INSERT,UPDATE')
                    OR has_table_privilege(%s,c.oid,'DELETE')))
                OR has_table_privilege(%s,c.oid,'TRUNCATE,REFERENCES,TRIGGER')
                OR has_table_privilege(%s,c.oid,'TRUNCATE,REFERENCES,TRIGGER')) AS private_access
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=ANY(%s) AND c.relkind IN ('r','p')""",
            (
                self.app_role,
                self.app_role,
                self.app_role,
                self.worker_role,
                self.app_role,
                [
                    "access.organizations",
                    "links.pools",
                    "platform.audit_events",
                    "platform.command_receipts",
                ],
                self.worker_role,
                self.worker_role,
                self.app_role,
                self.worker_role,
                [*_OWNED_SCHEMAS, _MIGRATION_SCHEMA],
            ),
        ).fetchone()
        if private_access is None or private_access[0]:
            raise SchemaError("Links runtime grants violate role separation")
        return SchemaStatus(
            revision="1",
            tables=tuple(sorted(tables)),
            functions=tuple(sorted(functions)),
        )

    def _history(
        self,
        connection: Connection[tuple[Any, ...]],
    ) -> tuple[tuple[object, ...], ...]:
        row = connection.execute(
            "SELECT pg_catalog.to_regclass(%s)",
            (f"{_MIGRATION_SCHEMA}.flyway_schema_history",),
        ).fetchone()
        if row is None:
            raise SchemaError("Links Flyway history lookup returned no result")
        exists = row[0]
        if exists is None:
            return ()
        return tuple(
            connection.execute(
                f"""
                SELECT version, script, success, type, checksum
                FROM {_MIGRATION_SCHEMA}.flyway_schema_history
                WHERE type IS DISTINCT FROM 'SCHEMA'
                ORDER BY installed_rank
                """
            ).fetchall()
        )

    @staticmethod
    def _owned_schemas(connection: Connection[tuple[Any, ...]]) -> frozenset[str]:
        names = connection.execute(
            """
            SELECT nspname
            FROM pg_catalog.pg_namespace
            WHERE nspname = ANY(%s)
            """,
            ([*_OWNED_SCHEMAS, _MIGRATION_SCHEMA],),
        ).fetchall()
        return frozenset(row[0] for row in names)

    def _policies(self) -> dict[tuple[str, str], tuple[object, ...]]:
        tenant = "(organization_id = platform.current_organization_id())"
        values: dict[tuple[str, str], tuple[object, ...]] = {
            (table, name): ("*", True, ("public",), tenant, tenant)
            for table, name in (
                ("access.organizations", "organizations_tenant_scope"),
                ("links.pools", "pools_tenant_scope"),
                ("links.links", "links_tenant_scope"),
                ("links.subscriptions", "subscriptions_tenant_scope"),
                ("platform.audit_events", "audit_events_tenant_scope"),
                ("platform.command_receipts", "command_receipts_tenant_scope"),
            )
        }
        worker = (self.worker_role,)
        values.update(
            {
                ("links.subscriptions", "subscriptions_worker_read"): (
                    "r",
                    True,
                    worker,
                    "true",
                    None,
                ),
                ("links.subscriptions", "subscriptions_worker_delete"): (
                    "d",
                    True,
                    worker,
                    "true",
                    None,
                ),
                ("links.links", "links_worker_active_read"): (
                    "r",
                    True,
                    worker,
                    "(is_active AND (destination_url IS NOT NULL))",
                    None,
                ),
                ("platform.activation_emails", "activation_emails_worker_access"): (
                    "*",
                    True,
                    worker,
                    "true",
                    "true",
                ),
            }
        )
        return values

    @staticmethod
    def _role(value: str) -> str:
        if not isinstance(value, str) or _ROLE_PATTERN.fullmatch(value) is None:
            raise ValueError("Links database roles must match links_[a-z][a-z0-9_]{0,24}")
        return value


__all__ = ["SchemaAuthority", "SchemaError", "SchemaStatus"]
