# Test deployments on Vercel

Deploy the same FastAPI application as the container build, with an explicit
serverless runtime profile. This guide prepares a **separate test environment**;
it does not provision a database, register Identity clients, or deploy anything
on your behalf. Keep the existing production database and Identity clients out
of the preview project.

## What runs where

| Component | Test deployment |
| --- | --- |
| API, OIDC callback, SSR dashboard and public redirects | One native Python 3.14 FastAPI function |
| Link data and schema revision | External PostgreSQL 18, using a direct TLS connection |
| Login attempts, browser sessions and DPoP replay records | External Redis over TLS, using its TCP protocol |
| Click recording | Inline, within the request transaction; no ARQ consumer required |
| Alembic and organization binding | Explicit operator steps before serving requests |
| Retention cleanup and other scheduled work | Separate persistent worker when required; not started in the function |

`DEPLOYMENT_MODE=serverless` selects `NullPool` for PostgreSQL and the inline
click adapter. Context use cases do not know which deployment is selected.
Redis is still mandatory for authentication. A REST-only Redis integration is
not interchangeable with a `rediss://` endpoint; the store needs atomic GETDEL
and SET-with-NX/expiry semantics.

Do not place a SQLite file in `/tmp` as persistent storage, start an ARQ worker
inside a function, or enqueue core preview clicks without a consumer. This profile
does not implement the future activation-email/outbox feature. Generic inherited
webhook and marketing operations remain unavailable in the Identity profile.

## 1. Prepare isolated dependencies and one stable origin

Create a dedicated PostgreSQL 18 database and Redis instance/database. Use the
database's **direct connection endpoint**, not a transaction-pooling URL unless
its asyncpg prepared-statement behavior has been separately validated. The
serverless profile does not retain SQL connections between invocation lifecycles;
concurrency still consumes database connections, so keep the preview modest.

Use verified TLS: the SQLAlchemy URL must have the `postgresql+asyncpg://` scheme
and `?ssl=verify-full`. Percent-encode reserved characters in usernames/passwords.
A provider's generic `sslmode` connection option is not used by this configuration.
The Redis URL must use `rediss://`.

Select one stable HTTPS origin for this test instance, such as an assigned branch
alias or a dedicated preview domain. It must be the origin users actually visit.
Do not infer the trusted origin from `Host`, `X-Forwarded-*`, or a deployment URL
inside application code. Changing to another alias requires an explicit config
change and a matching Identity callback registration.

Register a **test** Links API resource, scopes, confidential browser client and
organization in Identity as described in [IDENTITY.md](IDENTITY.md). In particular:

- `IDENTITY_AUDIENCE` is the API resource, not the browser client ID.
- The callback is exactly `IDENTITY_PUBLIC_BASE_URL/auth/callback`.
- The browser client uses the authorization-code flow, S256 PKCE,
  `client_secret_basic`, `openid` and the Links scopes; its access token is unbound.
- M2M clients use the separate, organization-bound token contract documented there.

The automated issuer fixture is not a deployed Identity service and is never a
fallback for a missing production issuer.

## 2. Configure the project

Use the repository root, select the **FastAPI** framework preset and deploy the
PR branch `feat/identity-core-link-flow` until it is merged. Do not select a
frontend framework or set an npm start command/output directory.

The checked-in files define the build:

- `vercel.json` selects FastAPI and a 30-second maximum function duration.
- `[tool.vercel].entrypoint` selects `app.index:app` explicitly.
- `app/index.py` exports the same ASGI application as the container; `api/index.py`
  remains an import alias for existing tooling, without changing `sys.path`.
- `.python-version` selects 3.14; `pyproject.toml` still requires Python >=3.14.
- `uv.lock` contains the runtime dependency resolution. Vercel's native Python
  builder can use uv 0.10.11; regular development/CI uses 0.12.21. The build backend
  remains `uv_build>=0.12.21,<0.13`, independent of the manager binary version.
- `[tool.vercel.scripts].build` runs a **read-only** configuration/asset check.
- `.vercelignore` and function exclusions remove development files, not templates,
  local CSS, `alembic.ini`, migration scripts or the lockfile.

Do not restore the old catch-all rewrite to `/api/index.py`: the native framework
routes the application. The API and callback paths must stay intact for OIDC and
DPoP request-URI verification. No credentials are stored in `vercel.json`.

In **Project Settings → Environment Variables**, configure the values from
[`infrastructure/.env.vercel.example`](../infrastructure/.env.vercel.example).
Scope them to this project's **Preview** environment/branch, with a separate set
for any future production deployment. Use the project's secret-value controls for
password-bearing URLs, `SECRET_KEY` and `IDENTITY_CLIENT_SECRET`.

Set `ENVIRONMENT=production` even though Vercel calls the deployment Preview. The
first controls application security; the second is the provider's environment
selector. Set `AUTH_MODE=identity`, `DEPLOYMENT_MODE=serverless` and
`IDENTITY_ALLOW_INSECURE_LOOPBACK=false`. All three must be available at build
and runtime; the read-only build check deliberately rejects incomplete settings.
Changing provider environment variables requires a new deployment.

For a local operator copy, keep secrets in an ignored file:

```sh
cp infrastructure/.env.vercel.example .env.preview
# Edit .env.preview and replace every placeholder before continuing.
uv python install 3.14
uv sync --locked
uv run --locked python -c 'import secrets; print(secrets.token_hex(32))'
```

Generate a real `SECRET_KEY` and store it in both the local operator configuration
and the project's Preview variables. Do not paste secret values into command-line
flags, documentation, callback URLs or commits.

## 3. Migrate and bind the tenant explicitly

From a machine that can reach the **test database**:

```sh
uv run --env-file .env.preview --locked alembic upgrade head
uv run --env-file .env.preview --locked alembic check
uv run --env-file .env.preview --locked plazia-links bind-organization \
  org_0199a112-3456-7000-8000-000000000001 --name 'Links preview'
uv run --env-file .env.preview --locked python -m app.platform.serverless
```

Replace the example organization with one actually issued by your Identity
environment. The command creates a local binding, not an Identity organization.
A second run is idempotent. Database DDL and tenant creation do **not** run in a
Vercel build, OIDC callback or cold start. Coordinate schema upgrades explicitly;
a build may succeed while the runtime correctly refuses an unmigrated database.
Do not change a populated PostgreSQL 16/17 image to 18 without a database upgrade.

## 4. Build and deploy the test instance

Use the project's Git integration to deploy the configured branch after the
previous steps. Alternatively, with an authenticated Vercel CLI and the project
already linked to this working copy:

```sh
vercel pull --environment=preview --git-branch=feat/identity-core-link-flow
vercel build
vercel deploy --prebuilt
```

These commands create a deployment in **your** account. They are instructions,
not a claim that a provider build/deployment has already been executed. The CLI
is build/deployment tooling; the application server remains Python.

Ensure the assigned stable origin points at that deployment. Platform deployment
protection may intercept public redirects, API clients or OIDC callbacks before
FastAPI sees them. Configure test access deliberately; never embed a provider
protection-bypass secret into links or browser application code.

## 5. Verify before sharing

Open `/health` at the configured origin: expect 200 only when PostgreSQL and Redis
are reachable. `/health/live` is liveness, not a database/Identity readiness test.
Then visit `/login`, sign in, create a link, edit its destination, open the public
short link, sign out and confirm the old session no longer grants dashboard
access. Test with a second tenant to verify isolation.

Unauthenticated `/api/v1/links` must return 401. Test an appropriate service token
with the configured audience and organization; use a fresh DPoP proof for each
request when the access token is bound. Production `/docs` and `/openapi.json`
are disabled by design. Database and client secrets must never appear in HTML.

Automated tests protect core dependency boundaries, validate configuration and
exercise both container/serverless ASGI profiles through a real browser. They do
not replace an authenticated Vercel build or a smoke test with your real Identity
issuer. The CI compatibility job is included so the supported uv manager, bundle
inputs and read-only preflight can be checked independently of account secrets.

## Troubleshooting and cleanup

| Symptom | Check |
| --- | --- |
| Build preflight rejects configuration | Preview variables exist at build time; all placeholders were replaced; HTTPS/TLS settings match the template |
| Runtime refuses startup | Run the migrations against the same database configured in Vercel; inspect connection/TLS errors without logging credentials |
| Callback fails or CSRF is rejected | Actual visited origin, configured public base URL and registered callback match exactly |
| API returns 403 after valid sign-in | Enabled `(issuer, organization)` binding and correct scopes |
| Redirect works but no queued clicks appear | Expected: the serverless profile records them inline |
| TLS/Redis errors | Direct PostgreSQL URL with `ssl=verify-full`; native Redis TCP/TLS endpoint, not an HTTP bridge |

Disable the preview organization binding and revoke the dedicated client before
disposing of the test environment. Delete only resources known to belong to this
preview; never reset shared volumes or databases to work around startup errors.

## Provider references

- [Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python)
- [Native FastAPI deployment](https://vercel.com/docs/frameworks/backend/fastapi)
- [Environment-variable scope](https://vercel.com/docs/environment-variables)
- [Vercel CLI pull/build environment](https://vercel.com/docs/cli/pull)
- [Native Python entrypoint resolver](https://github.com/vercel/vercel/blob/main/packages/python/src/entrypoint.ts)
- [Native Python uv manager selection](https://github.com/vercel/vercel/blob/main/packages/python/src/uv.ts)
