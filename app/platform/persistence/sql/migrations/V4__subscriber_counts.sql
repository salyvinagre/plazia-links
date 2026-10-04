-- Tenant RLS applies; the API can count subscriptions without reading subscriber identities.
GRANT SELECT (organization_id, link_id) ON links.subscriptions TO "${appRole}";
