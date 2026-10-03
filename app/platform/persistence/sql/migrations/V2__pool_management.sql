-- Pool deletion owns the lifecycle of its links and their dependent subscriptions.
ALTER TABLE links.links DROP CONSTRAINT fk_links_pool_organization;
ALTER TABLE links.links ADD CONSTRAINT fk_links_pool_organization
    FOREIGN KEY (organization_id, pool_id)
    REFERENCES links.pools (organization_id, id)
    ON DELETE CASCADE;

GRANT UPDATE, DELETE ON links.pools TO "${appRole}";
