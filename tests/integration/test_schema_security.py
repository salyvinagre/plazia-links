"""Startup refuses security drift in an otherwise migrated disposable database."""

import pytest
from psycopg import Connection, sql

from app.platform.persistence.schema import SchemaAuthority, SchemaError
from tests.integration.test_postgres_links import postgres_urls as postgres_urls


@pytest.mark.slow
@pytest.mark.parametrize(
    ("change", "restore", "runtime", "reason"),
    [
        (
            "GRANT SELECT ON platform.command_receipts TO links_worker",
            "REVOKE SELECT ON platform.command_receipts FROM links_worker",
            "worker",
            "role separation",
        ),
        (
            "GRANT SELECT ON platform.audit_events TO links_worker",
            "REVOKE SELECT ON platform.audit_events FROM links_worker",
            "worker",
            "role separation",
        ),
        (
            "GRANT DELETE ON links.pools TO links_app",
            "REVOKE DELETE ON links.pools FROM links_app",
            "app",
            "role separation",
        ),
        (
            "GRANT TRUNCATE ON links.links TO links_app",
            "REVOKE TRUNCATE ON links.links FROM links_app",
            "app",
            "role separation",
        ),
        (
            "GRANT links_worker TO links_app",
            "REVOKE links_worker FROM links_app",
            "app",
            "dedicated role",
        ),
        (
            "GRANT links_app TO links_worker",
            "REVOKE links_app FROM links_worker",
            "worker",
            "dedicated role",
        ),
        (
            "ALTER TABLE links.links OWNER TO links_app",
            "ALTER TABLE links.links OWNER TO {}",
            "app",
            "ownership",
        ),
        (
            "ALTER FUNCTION links.subscribe_reserved_link(uuid,text) OWNER TO links_app",
            "ALTER FUNCTION links.subscribe_reserved_link(uuid,text) OWNER TO {}",
            "app",
            "ownership",
        ),
        (
            "ALTER POLICY links_tenant_scope ON links.links USING(true) WITH CHECK(true)",
            "ALTER POLICY links_tenant_scope ON links.links "
            "USING(organization_id=platform.current_organization_id()) "
            "WITH CHECK(organization_id=platform.current_organization_id())",
            "app",
            "policies",
        ),
        (
            "ALTER FUNCTION links.subscribe_reserved_link(uuid,text) SECURITY INVOKER",
            "ALTER FUNCTION links.subscribe_reserved_link(uuid,text) SECURITY DEFINER",
            "app",
            "security functions",
        ),
        (
            "GRANT SELECT(email) ON links.subscriptions TO links_app",
            "REVOKE SELECT(email) ON links.subscriptions FROM links_app",
            "app",
            "role separation",
        ),
        (
            "GRANT EXECUTE ON FUNCTION links.subscribe_reserved_link(uuid,text) TO PUBLIC",
            "REVOKE EXECUTE ON FUNCTION links.subscribe_reserved_link(uuid,text) FROM PUBLIC",
            "app",
            "ownership",
        ),
        (
            "UPDATE links_migrations.flyway_schema_history "
            "SET checksum=checksum+1 WHERE version='1'",
            "UPDATE links_migrations.flyway_schema_history "
            "SET checksum=checksum-1 WHERE version='1'",
            "app",
            "history",
        ),
    ],
)
def test_runtime_rejects_security_drift(postgres_urls, change, restore, runtime, reason):
    url = postgres_urls.app if runtime == "app" else postgres_urls.worker
    authority = SchemaAuthority(url)
    assert authority.check(runtime=runtime).revision == "1"
    with Connection.connect(postgres_urls.owner, autocommit=True) as owner:
        name = owner.execute(
            "SELECT pg_catalog.pg_get_userbyid(nspowner) FROM pg_catalog.pg_namespace "
            "WHERE nspname='links'"
        ).fetchone()[0]
        try:
            owner.execute(change)
            with pytest.raises(SchemaError, match=reason):
                authority.check(runtime=runtime)
        finally:
            owner.execute(sql.SQL(restore).format(sql.Identifier(name)))
    assert authority.check(runtime=runtime).revision == "1"
