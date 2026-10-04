"""Startup refuses security drift in an otherwise migrated disposable database."""

import pytest
from psycopg import Connection, sql
from shared_persistence.roles import PostgresRoles

from app.platform.persistence.schema import SchemaAuthority, SchemaError
from tests.integration.test_postgres_links import postgres_urls as postgres_urls


@pytest.mark.slow
@pytest.mark.parametrize(
    ("change", "restore", "runtime", "reason"),
    [
        (
            "GRANT UPDATE(name) ON access.organizations TO links_app",
            "REVOKE UPDATE(name) ON access.organizations FROM links_app",
            "app",
            "role separation",
        ),
        (
            "GRANT UPDATE(destination_url) ON links.links TO links_worker",
            "REVOKE UPDATE(destination_url) ON links.links FROM links_worker",
            "worker",
            "role separation",
        ),
        (
            "GRANT INSERT ON links.subscriptions TO links_app",
            "REVOKE INSERT ON links.subscriptions FROM links_app",
            "app",
            "role separation",
        ),
        (
            "GRANT UPDATE(email) ON links.subscriptions TO links_app",
            "REVOKE UPDATE(email) ON links.subscriptions FROM links_app",
            "app",
            "role separation",
        ),
        (
            "GRANT DELETE ON links.subscriptions TO links_app",
            "REVOKE DELETE ON links.subscriptions FROM links_app",
            "app",
            "role separation",
        ),
        (
            "GRANT UPDATE(email) ON links.subscriptions TO links_worker",
            "REVOKE UPDATE(email) ON links.subscriptions FROM links_worker",
            "worker",
            "role separation",
        ),
        (
            "GRANT SELECT(link_id) ON links.subscriptions TO PUBLIC",
            "REVOKE SELECT(link_id) ON links.subscriptions FROM PUBLIC",
            "app",
            "public grants",
        ),
        (
            "REVOKE SELECT(link_id) ON links.subscriptions FROM links_app",
            "GRANT SELECT(link_id) ON links.subscriptions TO links_app",
            "app",
            "statistics grants",
        ),
        (
            "GRANT UPDATE(redirects) ON links.statistics TO links_app",
            "REVOKE UPDATE(redirects) ON links.statistics FROM links_app",
            "app",
            "role separation",
        ),
        (
            "GRANT SELECT ON links.statistics TO links_worker",
            "REVOKE SELECT ON links.statistics FROM links_worker",
            "worker",
            "role separation",
        ),
        (
            "GRANT EXECUTE ON FUNCTION links.record_visit(uuid,text,text) TO links_worker",
            "REVOKE EXECUTE ON FUNCTION links.record_visit(uuid,text,text) FROM links_worker",
            "worker",
            "statistics grants",
        ),
        (
            "GRANT EXECUTE ON FUNCTION links.record_visit(uuid,text,text) TO PUBLIC",
            "REVOKE EXECUTE ON FUNCTION links.record_visit(uuid,text,text) FROM PUBLIC",
            "app",
            "ownership",
        ),
        (
            "ALTER POLICY statistics_tenant_scope ON links.statistics USING(true) WITH CHECK(true)",
            "ALTER POLICY statistics_tenant_scope ON links.statistics "
            "USING(organization_id=platform.current_organization_id()) "
            "WITH CHECK(organization_id=platform.current_organization_id())",
            "app",
            "policies",
        ),
        (
            "ALTER TABLE links.statistics DROP CONSTRAINT fk_statistics_link_organization",
            "ALTER TABLE links.statistics ADD CONSTRAINT fk_statistics_link_organization "
            "FOREIGN KEY (organization_id,link_id) REFERENCES links.links(organization_id,id) "
            "ON DELETE CASCADE",
            "app",
            "deletion constraints",
        ),
        (
            "REVOKE SELECT ON links.statistics FROM links_app",
            "GRANT SELECT ON links.statistics TO links_app",
            "app",
            "statistics grants",
        ),
        (
            "ALTER ROLE links_app CREATEDB",
            "ALTER ROLE links_app NOCREATEDB",
            "app",
            "privileges",
        ),
        (
            "ALTER ROLE links_worker INHERIT",
            "ALTER ROLE links_worker NOINHERIT",
            "worker",
            "inheritance",
        ),
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
            "GRANT DELETE ON links.pools TO links_worker",
            "REVOKE DELETE ON links.pools FROM links_worker",
            "worker",
            "role separation",
        ),
        (
            "REVOKE UPDATE ON links.pools FROM links_app",
            "GRANT UPDATE ON links.pools TO links_app",
            "app",
            "pool management",
        ),
        (
            "ALTER TABLE links.links DROP CONSTRAINT fk_links_pool_organization",
            "ALTER TABLE links.links ADD CONSTRAINT fk_links_pool_organization "
            "FOREIGN KEY (organization_id,pool_id) REFERENCES links.pools(organization_id,id) "
            "ON DELETE CASCADE",
            "app",
            "deletion constraints",
        ),
        (
            "ALTER TABLE links.subscriptions DROP CONSTRAINT fk_subscriptions_link_organization",
            "ALTER TABLE links.subscriptions ADD CONSTRAINT fk_subscriptions_link_organization "
            "FOREIGN KEY (organization_id,link_id) REFERENCES links.links(organization_id,id) "
            "ON DELETE CASCADE",
            "app",
            "deletion constraints",
        ),
        (
            "ALTER TABLE platform.activation_emails "
            "DROP CONSTRAINT fk_activation_emails_link_organization",
            "ALTER TABLE platform.activation_emails "
            "ADD CONSTRAINT fk_activation_emails_link_organization "
            "FOREIGN KEY (organization_id,link_id) REFERENCES links.links(organization_id,id) "
            "ON DELETE CASCADE",
            "worker",
            "deletion constraints",
        ),
        (
            "ALTER TABLE platform.activation_emails "
            "DROP CONSTRAINT fk_activation_emails_subscription",
            "ALTER TABLE platform.activation_emails "
            "ADD CONSTRAINT fk_activation_emails_subscription "
            "FOREIGN KEY (organization_id,link_id,subscription_id) "
            "REFERENCES links.subscriptions(organization_id,link_id,id) ON DELETE CASCADE",
            "worker",
            "deletion constraints",
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
    assert authority.check(runtime=runtime).revision == "4"
    with Connection.connect(postgres_urls.owner, autocommit=True) as owner:
        roles = PostgresRoles.read(owner, owner="salyvinagre/plazia-links")
        for key in ("links_app", "links_worker"):
            change = change.replace(key, roles.names[key])
            restore = restore.replace(key, roles.names[key])
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
    assert authority.check(runtime=runtime).revision == "4"
