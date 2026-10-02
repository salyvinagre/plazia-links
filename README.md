# Plazia Links

An Identity-backed link-management service for Plazia, derived from
[Zly](https://github.com/PythonPlumber/zly). Create and edit short links through a
REST API or a small server-rendered dashboard. Public redirects remain independent
of an Identity round trip.

**Python ≥3.14 · uv · FastAPI · PostgreSQL 18 · Redis/ARQ · Jinja2**

> Pre-production. The core Identity integration has automated contract and browser
> tests, not a certification of a live deployment. Pools and activation notifications
> are not implemented. See [Identity setup and limits](docs/IDENTITY.md).

## Current scope

| Available in the Identity profile | Not exposed / planned |
| --- | --- |
| Create, list, edit, disable and delete links | Reserved codes and owned pools |
| Custom short codes, titles and internal notes | Visitor subscriptions and activation email |
| OIDC sign-in and server-side browser sessions | Token refresh and global SSO logout |
| Organization-bound API access and DPoP proofs | Fine-grained team/pool ownership rules |
| Versioned PostgreSQL migrations and a click worker | Inherited marketing/admin APIs and generic webhooks |

The intended next product flow is **reserve → share → subscribe → activate →
notify**. This repository does not simulate it with dummy destinations or marketing
contacts. The current link API requires a real destination.

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.12.21
(the development/CI version), Git and Docker Compose. From the repository root:

```sh
git clone https://github.com/salyvinagre/plazia-links.git
cd plazia-links
uv python install 3.14
uv sync --locked
cp .env.example .env
```

Edit `.env` with a database password, a random `SECRET_KEY`, and your product's
Identity issuer, API audience and confidential browser-client credentials. Keep
`DATABASE_URL`'s password aligned with `POSTGRES_PASSWORD`. The callback must be
registered as `IDENTITY_PUBLIC_BASE_URL/auth/callback`; the issuer and organization
are never inferred from an email address. Follow [the provisioning steps](docs/IDENTITY.md)
to register scopes, clients and an actual Identity organization first.

```sh
docker compose --env-file .env -f infrastructure/docker-compose.yml \
  -f infrastructure/compose.dev.yml up -d postgres redis
uv run --locked alembic upgrade head

# Replace the example with your existing Identity organization.
uv run --locked plazia-links bind-organization \
  org_0199a112-3456-7000-8000-000000000001 --name 'Example tenant'

uv run --locked uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

Start the click/retention worker in another terminal:

```sh
uv run --locked arq worker.run.WorkerSettings
```

Visit `http://localhost:8000/login`. The browser signs in at Identity, then returns
to `/dashboard/links`. The core dashboard uses native HTML forms; it does not
require a Node server, Svelte build, or browser access-token storage. Redis is
required for login sessions and DPoP replay protection, not merely an optional cache.

For isolated inherited-code development only, explicitly set `AUTH_MODE=legacy`.
There is no automatic fallback, and production API/worker startup rejects that mode.
The full inherited HTMX marketing dashboard is not part of the new deployed surface.

## REST API

The management surface is `/api/v1/links`; public links resolve at `/{short_code}`.
OpenAPI is available at `/openapi.json` and `/docs` in development. The schema and
interactive documentation are disabled in production.

| Method | Resource | Required scope |
| --- | --- | --- |
| `GET`, `POST` | `/api/v1/links` | `read:links`, `create:links` respectively |
| `GET`, `PATCH`, `DELETE` | `/api/v1/links/{id}` | `read:links`, `update:links`, `delete:links` respectively |

For an **unbound** Identity access token issued for the Links audience:

```sh
curl --fail-with-body http://localhost:8000/api/v1/links \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"destination_url":"https://example.com/page","title":"Example"}'
```

The tenant comes from the verified `org` claim and a locally enabled binding.
Do not send a `workspace_id` or organization selector in the body. The current
Identity M2M flow issues **DPoP-bound** tokens: those require
`Authorization: DPoP <token>` and a fresh signed `DPoP` header. The example above
is not a bearer downgrade for machine credentials. See [the token contract](docs/IDENTITY.md#rest-access).

## Serverless test deployment

The native Vercel profile runs the same Python 3.14 application with external
PostgreSQL 18 and Redis. `DEPLOYMENT_MODE=serverless` uses short-lived SQL
connections and records clicks within the request, so a preview does not depend
on an always-running ARQ worker. The API, OIDC callback and SSR form paths stay
unchanged; no catch-all rewrite or alternate authentication is introduced.

Follow [the Vercel test-deployment guide](docs/VERCEL.md) and use
[`infrastructure/.env.vercel.example`](infrastructure/.env.vercel.example).
Use a dedicated database, Redis namespace, Identity client and stable HTTPS
origin. Apply migrations and bind the tenant explicitly before serving traffic.
The build only validates configuration/assets; it never migrates a database.
The files and profile tests do not mean a live Vercel deployment has been executed.

## Container deployment

Copy `infrastructure/.env.example` to the root `.env`, replace all placeholders and
complete Identity provisioning. Its PostgreSQL and Redis hosts are the Compose
service names. Then:

```sh
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d --build
```

The stack includes PostgreSQL 18, Redis, a one-shot migration service, the API and
ARQ worker. The API listens on loopback port 8000; PostgreSQL and Redis have no
published ports in the base Compose file. Put a trusted HTTPS reverse proxy in
front, matching `IDENTITY_PUBLIC_BASE_URL`. Do not log auth callback query strings
or credentials. The optional Caddy profile requires deployment-specific configuration.

The runtime image uses Python 3.14, a non-root user and locked dependencies.
`/health/live` reports process liveness; `/health` returns 503 when PostgreSQL or,
in the Identity profile, Redis is unavailable. Startup requires a current Alembic
schema and complete Identity configuration; it never creates tables to conceal drift.

**Changing the PostgreSQL image is not a database upgrade.** PostgreSQL 18 uses
`/var/lib/postgresql/18/docker` within the volume mounted at `/var/lib/postgresql`.
Back up and migrate existing 16/17 data using a verified dump/restore or
`pg_upgrade` process. Never delete an existing volume to make startup succeed.
See [deployment details](docs/DEPLOYMENT.md).

## Validation

```sh
uv sync --locked --all-extras
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app/ worker/
uv run --locked pytest -q
uv build --no-sources
```

Fast tests use SQLite plus controlled boundary fakes. Identity acceptance tests
verify real signatures and exchange codes with a local HTTP issuer. CI separately
runs migrations and application tests on PostgreSQL 18, builds the production image,
and exercises Chromium with PostgreSQL and Redis. No live client credentials are
required for those tests.

For browser tests locally, set `POSTGRES_TEST_URL` to a **dedicated test database**,
set `REDIS_URL` to an isolated Redis database, and run:

```sh
DATABASE_URL="$POSTGRES_TEST_URL" uv run --locked alembic upgrade head
uv run --locked playwright install chromium
IDENTITY_E2E=1 uv run --locked pytest -q tests/e2e
```

The E2E suite starts its own local issuer and API process. It creates test workspaces
and links; never point it at production data. The ordinary pytest command skips
this opt-in browser job and PostgreSQL-specific tests, which run separately in CI.

## Architecture

The new `access` and `links` contexts separate domain invariants, application
use cases/ports and technical adapters. Session policy and link allocation live
in application services, not HTTP/SQL adapters. The platform binds implementations;
interfaces use published contracts. Architecture tests protect those dependencies.
See [the architecture and explicit legacy boundary](docs/ARCHITECTURE.md).

## Boundaries and remaining work

The authorization policy currently combines an enabled local organization binding
with scoped access to that workspace. There is no first-user ownership inference,
per-link sharing policy or online upstream revocation check on every request. Use
short-lived tokens; sessions expire no later than the verified token. Logout ends
the Links session, not the global Identity session.

Unfinished inherited custom-domain verification, outbound URL probes and webhooks
are absent from the Identity management surface; generic webhook delivery jobs are
also disabled. Their future reintroduction requires DNS/redirect-aware protection
and durable delivery semantics. Redirect caching remains disabled until it can
respect mutable link policy. Existing advanced link settings must be audited when
migrating pre-existing data.

## License and provenance

MIT. The original Zly license and copyright remain in [LICENSE](LICENSE).
[UPSTREAM.md](docs/UPSTREAM.md) records the imported commit and preserved histories;
[STABILIZATION.md](docs/STABILIZATION.md) records the baseline maintenance work.
This fork integrates upstream changes explicitly, not through automatic tracking.
