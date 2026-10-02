# Plazia Links

Self-hosted link management for Plazia, built on the Python backend and web
interface of [Zly](https://github.com/PythonPlumber/zly). This repository is an
independently maintained fork, not a release of the upstream marketing platform.

> **Status: stabilization / pre-production.** The existing shortening API is being
> hardened before adding Plazia Identity and reserved-link pools. A green CI is
> not a production-security approval. See [known limitations](#known-limitations).

## What is available

| Capability | Current state |
| --- | --- |
| Short links, custom codes, updates and deletion | Existing REST API |
| Expiration, passwords, tags, folders, QR codes and click analytics | Inherited functionality with regression coverage for the core flows |
| Web administration | Jinja2/HTMX pages; browser form integration still needs work |
| PostgreSQL schema and service startup | Versioned Alembic migrations; startup checks, no automatic DDL |
| Background processing | ARQ worker for clicks and existing email/webhook jobs |
| Plazia Identity | Planned; the application still uses its original authentication |
| Owned pools, unassigned links and activation subscriptions | Planned; not implemented |

The intended Plazia workflow is **reserve a pool → share a link → collect a
confirmed email subscription → assign a destination → notify the subscriber**.
Do not simulate this today with a dummy destination or a marketing contact:
those domain concepts will have their own API and persistence.

## Stack

**Python ≥3.14 · uv/uv_build · FastAPI · PostgreSQL 18 · SQLAlchemy async ·
Alembic · Redis/ARQ · Jinja2/HTMX.** There is no Node.js application server.

`uv.lock` is committed. Development and CI use `uv sync --locked`; production
builds install the same lock without development dependencies. `.python-version`
selects Python 3.14, while package metadata allows newer Python versions.

## Local development

Requirements: Git, [uv](https://docs.astral.sh/uv/getting-started/installation/)
**0.12.21 or newer**, and Docker with Compose for PostgreSQL and Redis. Run the
following from the repository root:

```sh
git clone https://github.com/salyvinagre/plazia-links.git
cd plazia-links
uv python install 3.14
uv sync --locked
cp .env.example .env
```

Edit `.env`: set a database password and two different random secrets. The
password in `DATABASE_URL` must match `POSTGRES_PASSWORD`. Generate a secret
without starting the application:

```sh
uv run --locked python -c 'import secrets; print(secrets.token_hex(32))'
```

Start the dependencies with loopback-only ports, migrate, and start the API:

```sh
docker compose --env-file .env -f infrastructure/docker-compose.yml \
  -f infrastructure/compose.dev.yml up -d postgres redis
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Run the worker in another terminal from the same directory:

```sh
uv run --locked arq worker.run.WorkerSettings
```

Open `http://localhost:8000/docs` for the API reference, or `/dashboard` for the
existing web UI. The latter is not yet an end-to-end verified administration
flow. Use `SECURE_COOKIES=false` only for local HTTP; HTTPS deployments must use
secure cookies. PostgreSQL is the supported application database; SQLite is
retained for the fast test suite, not as a production alternative.

## API and authentication

The management API is under `/api/v1`; public links resolve at `/{short_code}`.
In development the schema is available at `/openapi.json` and the interactive
reference at `/docs`. Interactive documentation is disabled in production.

The current API accepts **Bearer tokens from Zly's original login API** or its
workspace API keys. It does **not** yet accept Plazia Identity tokens. Ordinary
management calls are JSON, for example:

```sh
curl --fail-with-body http://localhost:8000/api/v1/links \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"workspace_id":"<workspace-id>","destination_url":"https://example.com"}'
```

Use `/docs` to register/login and obtain a workspace ID in an isolated development
instance. Never publish a shared administrative API key in a browser application.

## Container deployment

Use this only in an isolated evaluation environment until the limitations below
are resolved. Copy `infrastructure/.env.example` to the root `.env` and replace
all placeholders. Its database and Redis hosts are the Compose service names,
not `localhost`.

```sh
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d --build
```

The stack runs PostgreSQL 18, Redis, a one-shot migration service, the API and the
ARQ worker. The API binds only to `127.0.0.1:8000`. Put an existing reverse proxy
in front; the optional `tls` profile enables Caddy after its configuration has
been customized. Neither PostgreSQL nor Redis is published by the base Compose
file. The runtime image uses Python 3.14 and a non-root user.

**PostgreSQL major-version upgrades are not image-tag changes.** The PostgreSQL
18 image stores data under `/var/lib/postgresql/18/docker`; the volume is mounted
at `/var/lib/postgresql`. An existing 16/17 data directory must be migrated with
a verified dump/restore or `pg_upgrade` into a compatible layout. Back it up
first. Never remove an existing volume to make a failed upgrade start.

### Health checks

| Endpoint | Purpose |
| --- | --- |
| `/health/live` | Process liveness; no dependency checks |
| `/health` | Readiness: HTTP 503 if the database is unavailable; Redis degradation is reported |

Startup refuses an unapplied migration head. Migration failures must be corrected
before serving traffic, not hidden by creating tables at application startup.

## Tests and quality gates

```sh
uv sync --locked --all-extras
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app/ worker/
uv run --locked pytest -q
uv build --no-sources
```

The default unit/API suite uses SQLite and mocked boundaries. The PostgreSQL
runtime tests are opt-in locally and run against a freshly migrated **PostgreSQL
18** instance in CI. Point them only at a dedicated test database:

```sh
DATABASE_URL="$POSTGRES_TEST_URL" uv run --locked alembic upgrade head
DATABASE_URL="$POSTGRES_TEST_URL" uv run --locked alembic check
uv run --locked pytest -q tests/test_postgres_runtime.py
```

Set `POSTGRES_TEST_URL` beforehand to a dedicated PostgreSQL asyncpg URL. CI
checks lint, strict typing, tests, packaging, the production image and PostgreSQL
migrations independently. Failed checks are not skipped or downgraded to warnings.

## Known limitations

The current dashboard has unresolved form routing, encoding and authentication
integration. Custom-domain verification still needs real DNS ownership proof.
Outbound URL probes and webhooks need DNS/redirect-aware SSRF hardening, and
notification delivery needs a durable transactional outbox/retry path. Click
limits are not strict concurrency quotas. The unsafe redirect-destination cache
has been removed; Redis still serves jobs and analytics caches.

See [STABILIZATION.md](docs/STABILIZATION.md) for the remaining work and
[UPSTREAM.md](docs/UPSTREAM.md) for the imported source revision. Do not expose
unreviewed inherited marketing/admin features to untrusted tenants.

## License and upstream

MIT. The original Zly copyright and license are preserved in [LICENSE](LICENSE).
The fork imports `PythonPlumber/zly@master` while retaining both upstream Git
histories. Upstream fixes should be reviewed and integrated explicitly; this fork
does not automatically track an upstream branch.
