-- Fresh, organization-owned Links storage. Flyway is the only schema authority.

CREATE SCHEMA access;
CREATE SCHEMA links;
CREATE SCHEMA platform;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA access, links, platform FROM PUBLIC;

CREATE FUNCTION platform.current_organization_id() RETURNS uuid
    LANGUAGE sql STABLE
    SET search_path = pg_catalog
AS $$
    SELECT CASE
        WHEN current_setting('plazia.organization_id', true) ~ '^org_[0-9a-f]{32}$'
        THEN substring(current_setting('plazia.organization_id', true) FROM 5)::uuid
        ELSE NULL
    END
$$;

CREATE TABLE access.organizations (
    issuer text NOT NULL CHECK (length(issuer) BETWEEN 1 AND 2048),
    organization_id uuid NOT NULL,
    name text NOT NULL CHECK (length(name) <= 200),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT organizations_pkey PRIMARY KEY (issuer, organization_id),
    CONSTRAINT ck_organizations_uuidv7
        CHECK (uuid_extract_version(organization_id) IS NOT DISTINCT FROM 7)
);

CREATE TABLE links.pools (
    id uuid NOT NULL DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    name text CHECK (name IS NULL OR length(name) <= 200),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pools_pkey PRIMARY KEY (id),
    CONSTRAINT uq_pools_organization_id UNIQUE (organization_id, id),
    CONSTRAINT ck_pools_uuidv7
        CHECK (uuid_extract_version(id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_pools_organization_uuidv7
        CHECK (uuid_extract_version(organization_id) IS NOT DISTINCT FROM 7)
);

CREATE TABLE links.links (
    id uuid NOT NULL DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    pool_id uuid,
    short_code text NOT NULL,
    destination_url text,
    title text CHECK (title IS NULL OR length(title) <= 200),
    notes text CHECK (notes IS NULL OR length(notes) <= 4000),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT links_pkey PRIMARY KEY (id),
    CONSTRAINT uq_links_organization_id UNIQUE (organization_id, id),
    CONSTRAINT uq_links_short_code UNIQUE (short_code),
    CONSTRAINT ck_links_uuidv7 CHECK (uuid_extract_version(id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_links_organization_uuidv7
        CHECK (uuid_extract_version(organization_id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_links_pool_uuidv7
        CHECK (pool_id IS NULL OR uuid_extract_version(pool_id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_links_short_code
        CHECK (short_code ~ '^[A-Za-z0-9_-]{3,10}$'),
    CONSTRAINT ck_links_url_length
        CHECK (destination_url IS NULL OR length(destination_url) BETWEEN 1 AND 8192),
    CONSTRAINT ck_links_reserved_pool
        CHECK (destination_url IS NOT NULL OR pool_id IS NOT NULL),
    CONSTRAINT fk_links_pool_organization
        FOREIGN KEY (organization_id, pool_id)
        REFERENCES links.pools (organization_id, id)
        ON DELETE RESTRICT
);

CREATE INDEX ix_links_organization_created
    ON links.links (organization_id, created_at DESC, id DESC);
CREATE INDEX ix_links_organization_pool_created
    ON links.links (organization_id, pool_id, created_at DESC, id DESC);

CREATE TABLE links.subscriptions (
    id uuid NOT NULL DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    link_id uuid NOT NULL,
    email text NOT NULL CHECK (length(email) BETWEEN 3 AND 320),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT subscriptions_pkey PRIMARY KEY (id),
    CONSTRAINT uq_subscriptions_link_email UNIQUE (link_id, email),
    CONSTRAINT uq_subscriptions_organization_link_id UNIQUE (organization_id, link_id, id),
    CONSTRAINT ck_subscriptions_uuidv7 CHECK (uuid_extract_version(id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_subscriptions_organization_uuidv7
        CHECK (uuid_extract_version(organization_id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_subscriptions_link_uuidv7
        CHECK (uuid_extract_version(link_id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_subscriptions_email_shape
        CHECK (email !~ '[[:space:]]' AND email ~ '^[^@]+@[^@]+$'),
    CONSTRAINT fk_subscriptions_link_organization
        FOREIGN KEY (organization_id, link_id)
        REFERENCES links.links (organization_id, id)
        ON DELETE CASCADE
);

CREATE INDEX ix_subscriptions_organization_link
    ON links.subscriptions (organization_id, link_id, created_at);

CREATE TABLE platform.activation_emails (
    id uuid NOT NULL DEFAULT uuidv7(),
    subscription_id uuid NOT NULL,
    link_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    sent_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT activation_emails_pkey PRIMARY KEY (id),
    traceparent text CHECK (traceparent IS NULL OR length(traceparent)=55),
    tracestate text CHECK (tracestate IS NULL OR length(tracestate)<=512),
    CONSTRAINT uq_activation_emails_subscription UNIQUE (subscription_id),
    CONSTRAINT ck_activation_emails_uuidv7
        CHECK (uuid_extract_version(id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_activation_emails_subscription_uuidv7
        CHECK (uuid_extract_version(subscription_id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_activation_emails_link_uuidv7
        CHECK (uuid_extract_version(link_id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_activation_emails_organization_uuidv7
        CHECK (uuid_extract_version(organization_id) IS NOT DISTINCT FROM 7),
    CONSTRAINT fk_activation_emails_link_organization
        FOREIGN KEY (organization_id, link_id)
        REFERENCES links.links (organization_id, id)
        ON DELETE CASCADE,
    CONSTRAINT fk_activation_emails_subscription
        FOREIGN KEY (organization_id, link_id, subscription_id)
        REFERENCES links.subscriptions (organization_id, link_id, id)
        ON DELETE CASCADE
);

CREATE INDEX ix_activation_emails_ready
    ON platform.activation_emails (next_attempt_at, created_at, id)
    WHERE sent_at IS NULL AND attempts < 5;

CREATE TABLE platform.command_receipts (
    organization_id uuid NOT NULL,
    issuer text NOT NULL,
    subject text NOT NULL,
    action text NOT NULL,
    key text NOT NULL CHECK (length(key) BETWEEN 1 AND 128),
    fingerprint text NOT NULL CHECK (length(fingerprint)=64),
    result jsonb,
    CONSTRAINT command_receipts_pkey PRIMARY KEY (organization_id,issuer,subject,action,key),
    CONSTRAINT fk_command_receipts_organization FOREIGN KEY (issuer,organization_id)
        REFERENCES access.organizations(issuer,organization_id) ON DELETE CASCADE
);
ALTER TABLE platform.command_receipts ENABLE ROW LEVEL SECURITY;
CREATE POLICY command_receipts_tenant_scope ON platform.command_receipts
    USING (organization_id = platform.current_organization_id())
    WITH CHECK (organization_id = platform.current_organization_id());
GRANT SELECT,INSERT,UPDATE ON platform.command_receipts TO "${appRole}";

CREATE TABLE platform.audit_events (
    id uuid NOT NULL DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    action text NOT NULL CHECK (length(action) BETWEEN 1 AND 100),
    resource_type text NOT NULL CHECK (resource_type IN ('link', 'pool')),
    resource_id uuid NOT NULL,
    actor_id text NOT NULL,
    actor_type text NOT NULL,
    principal_id text,
    principal_type text,
    request_id text NOT NULL,
    correlation_id text,
    source_channel text NOT NULL,
    traceparent text,
    tracestate text,
    idempotency_key text,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT audit_events_pkey PRIMARY KEY (id),
    CONSTRAINT ck_audit_events_uuidv7 CHECK (uuid_extract_version(id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_audit_events_organization_uuidv7
        CHECK (uuid_extract_version(organization_id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_audit_events_resource_uuidv7
        CHECK (uuid_extract_version(resource_id) IS NOT DISTINCT FROM 7)
);

CREATE INDEX ix_audit_events_organization_recorded
    ON platform.audit_events (organization_id, recorded_at DESC, id DESC);

ALTER TABLE access.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE links.pools ENABLE ROW LEVEL SECURITY;
ALTER TABLE links.links ENABLE ROW LEVEL SECURITY;
ALTER TABLE links.subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.activation_emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.audit_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY organizations_tenant_scope ON access.organizations
    USING (organization_id = platform.current_organization_id())
    WITH CHECK (organization_id = platform.current_organization_id());
CREATE POLICY pools_tenant_scope ON links.pools
    USING (organization_id = platform.current_organization_id())
    WITH CHECK (organization_id = platform.current_organization_id());
CREATE POLICY links_tenant_scope ON links.links
    USING (organization_id = platform.current_organization_id())
    WITH CHECK (organization_id = platform.current_organization_id());
CREATE POLICY subscriptions_tenant_scope ON links.subscriptions
    USING (organization_id = platform.current_organization_id())
    WITH CHECK (organization_id = platform.current_organization_id());
CREATE POLICY audit_events_tenant_scope ON platform.audit_events
    USING (organization_id = platform.current_organization_id())
    WITH CHECK (organization_id = platform.current_organization_id());

CREATE POLICY subscriptions_worker_read ON links.subscriptions
    FOR SELECT TO "${workerRole}" USING (true);
CREATE POLICY subscriptions_worker_delete ON links.subscriptions
    FOR DELETE TO "${workerRole}" USING (true);
CREATE POLICY links_worker_active_read ON links.links
    FOR SELECT TO "${workerRole}"
    USING (is_active AND destination_url IS NOT NULL);
CREATE POLICY activation_emails_worker_access ON platform.activation_emails
    FOR ALL TO "${workerRole}" USING (true) WITH CHECK (true);

CREATE FUNCTION links.resolve_public_link(p_short_code text, p_lock boolean DEFAULT false)
RETURNS TABLE (id uuid, short_code text, destination_url text, is_active boolean)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, links
AS $$
BEGIN
    IF p_lock THEN
        RETURN QUERY
        SELECT l.id, l.short_code, l.destination_url, l.is_active
        FROM links.links AS l
        WHERE l.short_code = p_short_code
        FOR UPDATE OF l;
    ELSE
        RETURN QUERY
        SELECT l.id, l.short_code, l.destination_url, l.is_active
        FROM links.links AS l
        WHERE l.short_code = p_short_code;
    END IF;
END
$$;

CREATE FUNCTION links.subscribe_reserved_link(p_link_id uuid, p_email text)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, links
AS $$
DECLARE
    target record;
BEGIN
    SELECT l.id, l.organization_id, l.is_active, l.destination_url
    INTO target
    FROM links.links AS l
    WHERE l.id = p_link_id
    FOR UPDATE OF l;

    IF NOT FOUND THEN
        RETURN 'missing';
    END IF;
    IF NOT target.is_active THEN
        RETURN 'disabled';
    END IF;
    IF target.destination_url IS NOT NULL THEN
        RETURN 'active';
    END IF;

    INSERT INTO links.subscriptions (organization_id, link_id, email)
    VALUES (target.organization_id, target.id, p_email)
    ON CONFLICT (link_id, email) DO NOTHING;
    RETURN 'waiting';
END
$$;

CREATE FUNCTION links.ready_subscriptions(p_organization_id uuid, p_link_id uuid,
    p_traceparent text, p_tracestate text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, links, platform
AS $$
BEGIN
    IF p_organization_id IS DISTINCT FROM platform.current_organization_id() THEN
        RAISE EXCEPTION 'organization scope does not match activation request'
            USING ERRCODE = '42501';
    END IF;

    INSERT INTO platform.activation_emails
        (subscription_id, link_id, organization_id, traceparent, tracestate)
    SELECT s.id, l.id, l.organization_id, p_traceparent, p_tracestate
    FROM links.links AS l
    JOIN links.subscriptions AS s
      ON s.organization_id = l.organization_id AND s.link_id = l.id
    WHERE l.organization_id = p_organization_id
      AND l.id = p_link_id
      AND l.is_active
      AND l.destination_url IS NOT NULL
    ON CONFLICT (subscription_id) DO NOTHING;
END
$$;

REVOKE ALL ON FUNCTION platform.current_organization_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION links.resolve_public_link(text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION links.subscribe_reserved_link(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION links.ready_subscriptions(uuid, uuid, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION platform.current_organization_id() TO "${appRole}", "${workerRole}";
GRANT EXECUTE ON FUNCTION links.resolve_public_link(text, boolean) TO "${appRole}";
GRANT EXECUTE ON FUNCTION links.subscribe_reserved_link(uuid, text) TO "${appRole}";
GRANT EXECUTE ON FUNCTION links.ready_subscriptions(uuid, uuid, text, text) TO "${appRole}";

GRANT USAGE ON SCHEMA access, links, platform TO "${appRole}";
GRANT SELECT ON access.organizations TO "${appRole}";
GRANT SELECT, INSERT ON links.pools TO "${appRole}";
GRANT SELECT, INSERT, UPDATE, DELETE ON links.links TO "${appRole}";
GRANT INSERT ON platform.audit_events TO "${appRole}";
GRANT USAGE ON SCHEMA links_migrations TO "${appRole}", "${workerRole}";
GRANT SELECT ON links_migrations.flyway_schema_history TO "${appRole}", "${workerRole}";

GRANT USAGE ON SCHEMA links, platform TO "${workerRole}";
GRANT SELECT (id, organization_id, link_id, email, created_at)
    ON links.subscriptions TO "${workerRole}";
GRANT DELETE ON links.subscriptions TO "${workerRole}";
GRANT SELECT (id, organization_id, pool_id, short_code, destination_url,
              is_active, created_at, updated_at)
    ON links.links TO "${workerRole}";
GRANT SELECT ON platform.activation_emails TO "${workerRole}";
GRANT UPDATE (attempts, next_attempt_at, sent_at)
    ON platform.activation_emails TO "${workerRole}";
