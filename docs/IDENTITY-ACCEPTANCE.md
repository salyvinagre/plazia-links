# Identity-backed link management — acceptance boundary

This slice implements authenticated link management, not pools or notifications.
It retains Zly's CRUD implementation while replacing the deployed HTTP/auth surface.

- A browser completes authorization code + S256 PKCE against the configured Identity
  issuer. State is single-use and bound to the initiating browser; nonce and ID-token
  subject are verified. OAuth tokens never appear in browser storage or cookies.
- An operator explicitly binds one Identity issuer/organization to a local workspace.
  A signed token for an unbound organization grants no product access. Neither email
  nor a caller-selected workspace establishes that binding.
- Both browser forms and JSON API commands enforce the same scope ceiling and
  workspace-bound resource lookup. API credentials come only from Authorization.
- M2M clients use Identity's RFC 9068 access tokens and RFC 9449 DPoP binding. Proofs
  are checked against method, public request URL, access-token hash, time, JWK
  thumbprint and atomic replay state. A bound token is never treated as bearer.
- Browser sessions expire no later than the verified access token, use opaque
  HttpOnly cookies, and require a session-bound CSRF token for every mutation.
  Logout revokes the local session, not the user's global Identity session.
- Create, list, edit, delete and public redirect work end to end; validation errors
  render in the form. Public redirects do not call Identity.
- The Identity deployment does not expose legacy passwords, registration, local API
  keys, campaigns, custom-domain activation, link health checks or generic webhooks.
- Negative tests cover cross-tenant identifiers, scope denial, malformed/expired
  tokens, callback replay, nonce/subject mismatch, CSRF and revoked sessions.
- Chromium exercises sign-in, create, edit, redirect and logout against PostgreSQL 18
  and Redis, with a local standards-shaped test issuer, not a production account.
