-- Pixels identify email deliveries independently of short links and their destinations.
CREATE TABLE links.pixels (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    code text NOT NULL CONSTRAINT uq_pixels_code UNIQUE,
    reference text CHECK (reference IS NULL OR length(reference) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    requests bigint NOT NULL DEFAULT 0 CHECK (requests >= 0),
    first_requested_at timestamptz,
    last_requested_at timestamptz,
    CONSTRAINT ck_pixels_uuidv7 CHECK (uuid_extract_version(id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_pixels_organization_uuidv7
        CHECK (uuid_extract_version(organization_id) IS NOT DISTINCT FROM 7),
    CONSTRAINT ck_pixels_code CHECK (code ~ '^[A-Za-z0-9_-]{32}$'),
    CONSTRAINT ck_pixels_requests CHECK (
        (requests = 0 AND first_requested_at IS NULL AND last_requested_at IS NULL) OR
        (requests > 0 AND first_requested_at IS NOT NULL AND last_requested_at IS NOT NULL
            AND created_at <= first_requested_at AND first_requested_at <= last_requested_at)
    )
);
CREATE INDEX ix_pixels_organization_created
    ON links.pixels (organization_id,created_at DESC,id DESC);
ALTER TABLE links.pixels ENABLE ROW LEVEL SECURITY;
CREATE POLICY pixels_tenant_scope ON links.pixels
    USING (organization_id = platform.current_organization_id())
    WITH CHECK (organization_id = platform.current_organization_id());

ALTER TABLE platform.audit_events DROP CONSTRAINT audit_events_resource_type_check;
ALTER TABLE platform.audit_events ADD CONSTRAINT audit_events_resource_type_check
    CHECK (resource_type IN ('link','pool','pixel'));

CREATE FUNCTION links.resolve_public_pixel(p_code text) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, links
AS $$
    SELECT id FROM links.pixels WHERE code = p_code
$$;

CREATE FUNCTION links.record_pixel_request(p_id uuid, p_code text) RETURNS void
    LANGUAGE sql SECURITY DEFINER
    SET search_path = pg_catalog, links
AS $$
    UPDATE links.pixels SET requests = requests + 1,
        first_requested_at = coalesce(first_requested_at, clock_timestamp()),
        last_requested_at = greatest(last_requested_at, clock_timestamp())
    WHERE id = p_id AND code = p_code
$$;

REVOKE ALL ON links.pixels FROM PUBLIC;
REVOKE ALL ON FUNCTION links.resolve_public_pixel(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION links.record_pixel_request(uuid,text) FROM PUBLIC;
GRANT SELECT, DELETE ON links.pixels TO "${appRole}";
GRANT INSERT (organization_id,code,reference) ON links.pixels TO "${appRole}";
GRANT EXECUTE ON FUNCTION links.resolve_public_pixel(text) TO "${appRole}";
GRANT EXECUTE ON FUNCTION links.record_pixel_request(uuid,text) TO "${appRole}";
