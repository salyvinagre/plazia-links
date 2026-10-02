# Deployment: Python 3.14 and PostgreSQL 18

The maintained entry point is the [repository README](../README.md). Commands
below assume the repository root. This is a pre-production evaluation stack;
review [the outstanding security and UI work](STABILIZATION.md) before exposing it.

## Configuration

Copy `infrastructure/.env.example` to `.env`. Replace every password/secret,
configure `DEFAULT_DOMAIN` and `CORS_ORIGINS`, and keep `SECURE_COOKIES=true` for
HTTPS. `DATABASE_URL` uses the `postgres` service, and its password must match
`POSTGRES_PASSWORD`. `REDIS_URL` uses `redis`. The application tolerates the
Compose-only keys in this shared environment file.

```sh
docker compose --env-file .env -f infrastructure/docker-compose.yml config --quiet
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d --build
docker compose --env-file .env -f infrastructure/docker-compose.yml ps
```

The image is built from `python:3.14-slim` with uv 0.12.21. Both dependency layers
use `uv sync --locked --no-dev`; the final package is installed non-editably.
The final image runs as UID 10001. PostgreSQL 18 and Redis are private to the
Compose network. The API port is bound to the host loopback interface.

The one-shot `migrate` service must succeed before the API and worker start.
There are no startup `create_all` calls or ad-hoc ALTER statements. `/health`
reports database readiness; `/health/live` checks only process liveness.

## Reverse proxy

Use the existing reverse proxy for the deployment, or customize
`infrastructure/Caddyfile` and enable the optional `tls` profile. The included
Caddyfile is a placeholder, not automatic domain provisioning. When the proxy
runs in another container, attach it to the application network and route to
`fastapi:8000`; a container's `localhost` is not the host's loopback address.

## PostgreSQL 16/17 to 18

The official PostgreSQL 18 image uses `PGDATA=/var/lib/postgresql/18/docker` and
mounts the parent `/var/lib/postgresql`. The application schema migrations and
the PostgreSQL major-version upgrade are **different operations**.

For a populated older database: stop writers, take and verify a backup, restore
into a new PostgreSQL 18 volume (or use a separately tested `pg_upgrade`
procedure), apply Alembic, and verify row counts and representative links before
switching traffic. Retain the original volume for rollback. Do not point the
new image at an old-format data directory or delete a volume to bypass an error.

Official image layout: [PostgreSQL image documentation](https://github.com/docker-library/docs/blob/master/postgres/README.md#pgdata).

## Checks after deployment

```sh
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/health/live
docker compose --env-file .env -f infrastructure/docker-compose.yml exec fastapi alembic current
docker compose --env-file .env -f infrastructure/docker-compose.yml exec fastapi alembic check
docker compose --env-file .env -f infrastructure/docker-compose.yml logs --tail=100 fastapi worker
```

Test redirect and management requests separately. A healthy HTTP process does
not prove that SMTP, custom-domain ownership or webhook retries work. Exercise
the configured delivery path explicitly; activation subscriptions are not yet
implemented.

## Identity profile cutover

`AUTH_MODE=identity` is now the default. Configure the five `IDENTITY_*` trust/client
settings in the container environment and register the exact callback before
launching the service. Follow [IDENTITY.md](IDENTITY.md) for the issuer contract,
scopes, DPoP requirements and revocation limits. The previous Zly JWT/API-key login
is not an alternative credential path; production API and worker startup reject
`AUTH_MODE=legacy`.

After migration and startup, provision the local product binding explicitly:

```sh
docker compose --env-file .env -f infrastructure/docker-compose.yml exec fastapi \
  plazia-links bind-organization org_0199a112-3456-7000-8000-000000000001 \
  --name 'Example tenant'
```

Use the actual existing Identity organization. Add `--workspace-id` only when an
operator has reviewed and approved ownership of a pre-existing workspace. The
command does not create Identity customers, users or OAuth clients.

Redis is mandatory for opaque browser sessions and atomic DPoP replay protection.
Readiness fails if Redis is unavailable in this profile. Review/drain previous
marketing/webhook jobs before starting the restricted worker. Only click recording
and retention cleanup are registered in the Identity runtime.

Set `IDENTITY_PUBLIC_BASE_URL` to the exact external HTTPS origin. The reverse proxy
must preserve the API path; its forwarded Host headers are not authority inputs for
proof verification. Redact auth query strings, cookies and Authorization/DPoP
headers from proxy logs. The shipped Uvicorn command uses `--no-access-log`.
