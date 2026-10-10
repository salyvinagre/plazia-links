ALTER TABLE access.organizations ADD COLUMN workloads text[] NOT NULL DEFAULT '{}'
    CHECK (cardinality(workloads) <= 16);

ALTER TABLE links.pools ADD COLUMN entropy text CHECK (entropy IN ('low', 'medium', 'high')),
    ADD COLUMN visibility text NOT NULL DEFAULT 'organization' CHECK (visibility IN ('organization', 'workload_private')),
    ADD COLUMN owner_issuer text,
    ADD COLUMN owner_client text,
    ADD CHECK (visibility <> 'workload_private' OR (entropy IS NOT DISTINCT FROM 'high' AND owner_issuer IS NOT NULL AND owner_client IS NOT NULL));
ALTER TABLE links.links ADD COLUMN entropy text CHECK (entropy IN ('low', 'medium', 'high')),
    ADD COLUMN visibility text NOT NULL DEFAULT 'organization' CHECK (visibility IN ('organization', 'workload_private')),
    ADD COLUMN owner_issuer text,
    ADD COLUMN owner_client text,
    DROP CONSTRAINT ck_links_short_code,
    ADD CONSTRAINT ck_links_short_code CHECK (short_code ~ '^[A-Za-z0-9_-]{3,32}$'),
    ADD CHECK (entropy IS NULL OR length(short_code) = CASE entropy WHEN 'low' THEN 8 WHEN 'medium' THEN 20 WHEN 'high' THEN 32 END),
    ADD CHECK (visibility <> 'workload_private' OR (entropy IS NOT DISTINCT FROM 'high' AND owner_issuer IS NOT NULL AND owner_client IS NOT NULL));

CREATE FUNCTION links.guard_policy() RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
DECLARE pool links.pools;
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.owner_issuer := CASE WHEN NEW.visibility = 'workload_private'
            THEN nullif(current_setting('plazia.issuer', true), '') END;
        NEW.owner_client := CASE WHEN NEW.visibility = 'workload_private'
            THEN nullif(current_setting('plazia.client_id', true), '') END;
    END IF;
    IF TG_OP = 'UPDATE' AND
       ROW(OLD.entropy, OLD.visibility, OLD.owner_issuer, OLD.owner_client) IS DISTINCT FROM
       ROW(NEW.entropy, NEW.visibility, NEW.owner_issuer, NEW.owner_client) THEN
        RAISE check_violation USING MESSAGE = 'Issued link policy is immutable';
    END IF;
    IF TG_TABLE_NAME = 'links' THEN
        IF NEW.pool_id IS NOT NULL THEN
            SELECT * INTO pool FROM links.pools WHERE id = NEW.pool_id AND organization_id = NEW.organization_id FOR SHARE;
            IF NOT FOUND OR ROW(pool.entropy, pool.visibility, pool.owner_issuer, pool.owner_client) IS DISTINCT FROM
                ROW(NEW.entropy, NEW.visibility, NEW.owner_issuer, NEW.owner_client) THEN
                RAISE check_violation USING MESSAGE = 'Link policy must match its pool';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION links.guard_policy() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION links.guard_policy() TO "${appRole}";
CREATE TRIGGER links_policy BEFORE INSERT OR UPDATE ON links.links FOR EACH ROW EXECUTE FUNCTION links.guard_policy();
CREATE TRIGGER pools_policy BEFORE INSERT OR UPDATE ON links.pools FOR EACH ROW EXECUTE FUNCTION links.guard_policy();

CREATE POLICY links_workload_scope ON links.links AS RESTRICTIVE TO "${appRole}"
    USING (visibility = 'organization' OR (owner_issuer = current_setting('plazia.issuer', true) AND owner_client = current_setting('plazia.client_id', true)))
    WITH CHECK (visibility = 'organization' OR (owner_issuer = current_setting('plazia.issuer', true) AND owner_client = current_setting('plazia.client_id', true)));
CREATE POLICY pools_workload_scope ON links.pools AS RESTRICTIVE TO "${appRole}"
    USING (visibility = 'organization' OR (owner_issuer = current_setting('plazia.issuer', true) AND owner_client = current_setting('plazia.client_id', true)))
    WITH CHECK (visibility = 'organization' OR (owner_issuer = current_setting('plazia.issuer', true) AND owner_client = current_setting('plazia.client_id', true)));
CREATE POLICY statistics_workload_scope ON links.statistics AS RESTRICTIVE TO "${appRole}"
    USING (EXISTS (SELECT FROM links.links WHERE links.id = statistics.link_id));

ALTER TABLE platform.command_receipts
    ADD COLUMN client_id text NOT NULL DEFAULT '',
    ADD COLUMN expires_at timestamptz NOT NULL DEFAULT (clock_timestamp() + interval '7 days');
UPDATE platform.command_receipts SET expires_at = clock_timestamp();
ALTER TABLE platform.command_receipts DROP CONSTRAINT command_receipts_pkey,
    ADD PRIMARY KEY (organization_id, issuer, subject, client_id, action, key);
CREATE POLICY receipts_workload_scope ON platform.command_receipts AS RESTRICTIVE TO "${appRole}"
    USING (issuer = current_setting('plazia.issuer', true) AND client_id = current_setting('plazia.client_id', true))
    WITH CHECK (issuer = current_setting('plazia.issuer', true) AND client_id = current_setting('plazia.client_id', true));
