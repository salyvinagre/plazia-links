DO $$
DECLARE
    schema_count integer;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM links_migrations.flyway_schema_history
        WHERE version = '1' AND success
    ) THEN
        SELECT count(*) INTO schema_count
        FROM pg_catalog.pg_namespace
        WHERE nspname IN ('access', 'links', 'platform');
        IF schema_count > 0 THEN
            RAISE EXCEPTION
                'Unversioned Links schemas are unsupported; use a fresh Flyway target';
        END IF;
    END IF;
END
$$;
