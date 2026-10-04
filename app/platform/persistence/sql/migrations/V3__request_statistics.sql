-- Request aggregates are product reads; individual visitor data is not retained.
CREATE TABLE links.statistics_coverage (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO links.statistics_coverage (singleton) VALUES (true);

CREATE TABLE links.statistics (
    organization_id uuid NOT NULL,
    link_id uuid NOT NULL,
    redirects bigint NOT NULL DEFAULT 0 CHECK (redirects >= 0),
    waiting_views bigint NOT NULL DEFAULT 0 CHECK (waiting_views >= 0),
    last_visited_at timestamptz NOT NULL,
    PRIMARY KEY (organization_id, link_id),
    CONSTRAINT fk_statistics_link_organization
        FOREIGN KEY (organization_id, link_id)
        REFERENCES links.links (organization_id, id) ON DELETE CASCADE
);
ALTER TABLE links.statistics ENABLE ROW LEVEL SECURITY;
CREATE POLICY statistics_tenant_scope ON links.statistics
    USING (organization_id = platform.current_organization_id())
    WITH CHECK (organization_id = platform.current_organization_id());

CREATE FUNCTION links.record_visit(p_link_id uuid, p_code text, p_outcome text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, links
AS $$
DECLARE
    organization uuid;
BEGIN
    IF p_outcome NOT IN ('redirect', 'waiting') OR p_outcome IS NULL THEN
        RAISE EXCEPTION 'Invalid visit outcome' USING ERRCODE = '23514';
    END IF;
    SELECT l.organization_id INTO organization FROM links.links l
        WHERE l.id = p_link_id AND l.short_code = p_code AND l.is_active
        AND (l.destination_url IS NOT NULL) = (p_outcome = 'redirect')
        FOR KEY SHARE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    INSERT INTO links.statistics (organization_id, link_id, redirects, waiting_views, last_visited_at)
        VALUES (organization, p_link_id, (p_outcome = 'redirect')::int,
                (p_outcome = 'waiting')::int, clock_timestamp())
        ON CONFLICT (organization_id, link_id) DO UPDATE SET
            redirects = links.statistics.redirects + EXCLUDED.redirects,
            waiting_views = links.statistics.waiting_views + EXCLUDED.waiting_views,
            last_visited_at = greatest(links.statistics.last_visited_at, EXCLUDED.last_visited_at);
END
$$;

REVOKE ALL ON links.statistics, links.statistics_coverage FROM PUBLIC;
REVOKE ALL ON FUNCTION links.record_visit(uuid, text, text) FROM PUBLIC;
GRANT SELECT ON links.statistics, links.statistics_coverage TO "${appRole}";
GRANT EXECUTE ON FUNCTION links.record_visit(uuid, text, text) TO "${appRole}";
