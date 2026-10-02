# Identity integration

This deployment uses the documented `plazia-identity` OAuth/OIDC contract, not
Identity's private implementation packages. The shared `plazia-authlib` source
was not available in the current public portfolio repository; Links does not
introduce a sibling-checkout dependency or copy Identity internals.

OAuthlib owns PKCE and the code/token form parsing; HTTPX performs the
confidential exchange, and PyJWT with cryptography validates signatures. This is
a service-specific adapter, not a generic identity-provider framework.

## Provisioning

Register a Links API resource in the appropriate Identity business/environment.
Use its exact HTTPS resource identifier as `IDENTITY_AUDIENCE`. Register these
four scopes and grant only the necessary ones to each client:

| Scope | Product authority |
| --- | --- |
| `read:links` | List/read links in the explicitly bound organization |
| `create:links` | Create links there |
| `update:links` | Update their destinations, titles, notes and active status |
| `delete:links` | Delete links there |

Register a confidential browser client with `client_secret_basic`, authorization
code, S256 PKCE, `openid` and the needed Links scopes. Its exact callback is
`IDENTITY_PUBLIC_BASE_URL/auth/callback`. Configure this client for **unbound
Bearer access tokens**. Bound tokens are deliberately rejected by this browser
adapter rather than silently downgraded. There is no dynamic registration,
password grant, implicit flow, or tenant selector supplied by the browser.

Register service clients with Identity's organization-bound machine credentials.
Their `client_credentials` exchange requires the Links `resource` and a fresh
DPoP proof. Links does not issue client credentials or configure the Identity
server on the operator's behalf.

Set `IDENTITY_ISSUER`, `IDENTITY_AUDIENCE`, `IDENTITY_CLIENT_ID`,
`IDENTITY_CLIENT_SECRET` and `IDENTITY_PUBLIC_BASE_URL` in the Links environment.
The issuer and public base are origin URLs. All endpoint locations are derived
from that trusted issuer, never token headers, HTTP Host or caller-supplied
metadata:

- Authorization: `/oauth2/auth`
- Token: `/oauth2/token`
- Public signing keys: `/.well-known/jwks`

The audience must differ from the browser client ID. HTTPS is required. The
explicit `IDENTITY_ALLOW_INSECURE_LOOPBACK=true` exception permits only loopback
HTTP during non-production development; production rejects that configuration.

## Local organization binding

The Identity token's canonical `org_<uuidv7>` identifies the tenant. An operator
must bind it to a local workspace before any API or dashboard access succeeds:

```sh
uv run --locked plazia-links bind-organization \
  org_0199a112-3456-7000-8000-000000000001 --name 'Example tenant'
```

Replace the example with an organization that actually exists in your Identity
business. The command does **not** create an Identity organization. It creates
only a local product workspace and an active `(issuer, organization_id)` binding.
Repeated binding is idempotent; it may reactivate an explicitly disabled binding.
There are no local user/password replicas, fabricated user emails, implicit
first-user ownership, or cross-business email matching.

For an existing local workspace, pass `--workspace-id <uuid>` explicitly. A
workspace already bound to another issuer/organization cannot be reassigned by
this command. Back up an existing database and review ownership before binding it.

To revoke the local tenant's access, including existing browser sessions:

```sh
uv run --locked plazia-links disable-organization \
  org_0199a112-3456-7000-8000-000000000001
```

Every management request rechecks this binding. The authorization policy in this
slice is deliberately coarse: the binding grants participation, and the validated
scope limits allowed actions within that workspace. Per-link owners, team ACLs,
pool ownership, delegated roles and cross-organization sharing are not implemented.

## REST access

Only one `Authorization` header is accepted. Unbound tokens use `Bearer`;
`cnf.jkt` tokens require the `DPoP` scheme plus exactly one `DPoP` proof header.
Credentials in cookies, query strings or request bodies are not accepted.

Access tokens must satisfy the documented RS256 RFC 9068 profile: exact issuer,
Links audience, `typ=at+jwt` or `application/at+jwt`, nonempty `sub`, `client_id`,
`jti`, numeric `iat`/`exp`, canonical `org`, and a space-delimited `scope`.
ID tokens, opaque keys, local JWTs and alternate permission claims are rejected.
Signing-key resolution uses a bounded whole-JWKS cache (300 seconds), no
indefinite individual-key cache, and throttled unknown-key refreshes.

DPoP supports ES256/P-256 and RS256 public keys. Verification checks signature,
`typ=dpop+jwt`, method, externally configured request URI, token hash, thumbprint,
`iat` (120-second window, 5-second clock leeway) and an atomic Redis replay entry.
Query strings and fragments are excluded from the DPoP URI as required by the
protocol. A session/replay store outage fails closed. This initial verifier does
not demand a server-supplied DPoP nonce.

The public origin is configured explicitly so proof verification does not trust
arbitrary `X-Forwarded-*` headers. Deploy the application behind a reverse proxy
that serves that origin without rewriting the resource path. Protect its internal
listener; do not publish unrelated aliases as equivalent API audiences.

Token revocation or upstream membership changes are not checked through online
introspection on each request. A valid JWT may remain usable until expiry (with
5-second clock leeway); JWKS changes may take up to the cache TTL to propagate.
Use short-lived access tokens. Disabling the local organization binding takes
effect on the next management request. Immediate per-subject upstream revocation
would require an additional introspection/session-revocation integration.

## Browser sessions

The code flow uses independent random state, nonce and PKCE verifier. Redis holds
a ten-minute transaction keyed by the random browser cookie and state; GETDEL
consumes it once. The callback validates the ID token's issuer, audience, nonce,
subject, authorized party and access-token hash when provided. The verified
access token must belong to the configured browser client and a bound tenant.

The browser receives a new opaque HttpOnly session cookie, not OAuth tokens. Its
server-side record holds only the verified principal and CSRF secret. Session
lifetime is the minimum of access-token expiry, ID-token expiry and
`IDENTITY_SESSION_TTL` (900 seconds by default, at most 3600). There is no token
refresh in this slice: expired sessions restart the normal Identity flow.

Secure deployments use `__Host-` cookies with `Secure`, `HttpOnly`, `Path=/`, no
Domain attribute and SameSite=Lax. All mutations, including logout, require a
session-bound CSRF value and reject a foreign Origin. Templates autoescape user
content; the core dashboard uses native forms and local CSS, no token-handling JS.

Logout destroys the **local Links session**. It does not revoke the global
Identity SSO session. A subsequent login may reuse that SSO session.

Do not log callback query strings, Authorization/DPoP headers, cookies or token
responses. The shipped Uvicorn command disables access logging; configure the
reverse proxy likewise or redact query strings for auth routes.

## Limited deployed surface

`AUTH_MODE=identity` is the default. It mounts the core Links API and SSR routes,
not the inherited local registration, password login, local API keys, admin,
marketing, custom-domain activation, URL health-check or generic webhook APIs.
Generic webhook delivery is also disabled at the transport/worker boundaries;
the Identity worker registers only click recording and retention cleanup.

`AUTH_MODE=legacy` exists solely to exercise inherited code in isolated local
development and regression tests. Both API startup and worker startup reject it
in production. It is never selected automatically when Identity is unavailable.
Do not expose a legacy instance to untrusted users. Review/drain any old marketing
or webhook jobs before switching an existing queue to the restricted worker.

## Proof and limits

Acceptance tests use real RSA/EC signatures, a local HTTP JWKS/token endpoint and
an expiring fake store. The Chromium job uses real PostgreSQL 18 and Redis with
the same locally controlled standards-shaped issuer. It covers sign-in, create,
edit, public redirect, CSRF rejection, local logout, binding revocation and M2M
DPoP replay rejection. It is **not** a test against an already provisioned live
Plazia Identity deployment; that final issuer/client setup is operator-owned.

There is no reserved-link, pool, subscription, notification or outbox feature in
this slice. These will build on the verified principal and local tenant binding.
