# Identity and organization authority
Configure PLZK_IDENTITY_ISSUER, _AUDIENCE, _CLIENT_ID, _CLIENT_SECRET (or _CLIENT_SECRET_FILE), _PUBLIC_BASE_URL and optionally _SESSION_TTL. Issuer and public base are HTTPS origins. HTTP loopback is allowed only outside production with PLZK_IDENTITY_ALLOW_INSECURE_LOOPBACK=true. Resource audience is the canonical HTTPS /api/v1 base, distinct from the browser client ID. Local acceptance uses an explicitly synthetic HTTPS audience with a loopback transport origin.

Register a confidential authorization-code client with callback {public_base}/auth/callback and scopes openid links:read links:create links:update links:delete. Browser sessions are opaque handles stored in Redis; access/id tokens never reach browser storage. PKCE, browser-bound one-use state, nonce, ID/access subject match and optional at_hash are verified.

API credentials follow Identity's signed RS256 RFC9068 profile: typ at+jwt, matching iss/aud, canonical org UUIDv7, sub, client_id, scope, exp/iat and jti. Tokens with cnf.jkt must use DPoP and provide a valid proof for the configured public origin/path and HTTP method. Proof replay uses atomic Redis NX. Cookies never authorize the API. The protocol owner is `plazia_authlib.authn`: its OAuth client supplies the resource during the PKCE exchange, and its JWT reader validates access and ID token profiles. Links maps verified claims to its canonical principals, pins the credential destination, and owns browser sessions and the Redis replay store.

The portfolio OpenFGA organization model must contain reader and manager relations. User/machine subjects use shared canonical usr_/mch_ IDs. An owner/admin/business manager may mutate Links within its organization; organization reader authority permits reads. Tokens' client capabilities constrain every action independently. Checks use the configured immutable model ID and higher consistency, fail closed on invalid/unavailable decisions, and precede database reads. Links never writes membership tuples.

The API also checks an active local issuer+org binding. The operator binds the canonical organization directly; no local user, workspace, role or synthetic tenant is created at login. Existing management sessions lose access when authority or binding is revoked.

The shared action registry maps `links.read` to organization `reader` and `links.create`, `links.update`, and `links.delete` to organization `manager`. Links consumes that registry and the shared OpenFGA adapter with its own audit source. The existing organization graph and tuple ownership are preserved; product capability and active-binding guards remain in Links.


## Deployment ownership

Use the existing Plazia Identity business for the first Links deployment, with
its own Links API resource and confidential browser client. Their issuer,
audience, client ID and protected secret are deployment bindings; the Links
consumer does not create a business, Identity tenant, client, or OpenFGA model.
The API audience remains distinct from the browser client ID. Sharing the
provider business does not merge organization-owned pools or bypass membership
checks. A separate business becomes an explicit ownership decision when Links
needs its own operators, billing or security policy.

Bind an authorized Identity organization with the owner CLI after installation:
`PLZK_SCHEMA_DATABASE_URL` is the owner credential; `PLZK_DATABASE_URL` is always
the API credential. Provider installation and production acceptance remain open.

## Local testing

`tests/fixtures/identity.toml` declares the synthetic user and confidential
browser client. `plazia_authlib.testing.LocalIssuer` serves discovery, JWKS,
PKCE, and token exchange through the same signed-token authority used by direct
fixtures and Compliance's client-credentials tests. Links retains its content
fixture, settings, Redis state-store tests, and authorization graph locally.

`make test TEST_SUITE=fast` exercises the product authentication boundary.
`make acceptance` adds disposable PostgreSQL, Redis, OpenFGA, Mailpit, and
browser proof. These use fixture Identity tokens; actual Identity enrollment
and deployed acceptance remain separate evidence.
