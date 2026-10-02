# Plazia Links

A Plazia fork of [PythonPlumber/zly](https://github.com/PythonPlumber/zly),
using FastAPI, PostgreSQL, Jinja2/HTMX and ARQ. The upstream MIT license is
retained.

**Status: baseline stabilization, not a production-approved release.**
The active upstream `master` snapshot has been merged into `main` with both
Git histories preserved. See [upstream provenance](docs/UPSTREAM.md) and the
[stabilization report](docs/STABILIZATION.md) before deploying.

Pools of reserved links, visitor subscriptions, activation notifications and
Plazia Identity integration are planned product work, not shipped features.
The existing upstream dashboard still requires end-to-end integration fixes.

## Development and verification

Python 3.12+ is required. For an isolated environment:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
ruff check .
mypy app/ --ignore-missing-imports
```

The inherited unit suite uses SQLite and does not validate PostgreSQL migrations.
CI also runs `alembic upgrade head` and `alembic check` against fresh PostgreSQL.
Full-project lint/type debt is not hidden or disabled to make the checks green.

## Fresh PostgreSQL deployment for review

Copy `infrastructure/.env.example` to `.env` in the repository root and configure
all relevant values, including the following (replace every placeholder):

```dotenv
POSTGRES_USER=zly
POSTGRES_DB=zly
POSTGRES_PASSWORD=REPLACE_WITH_RANDOM_PASSWORD
DATABASE_URL=postgresql+asyncpg://zly:REPLACE_WITH_RANDOM_PASSWORD@postgres:5432/zly
REDIS_URL=redis://redis:6379/0
SECRET_KEY=REPLACE_WITH_RANDOM_SECRET_AT_LEAST_32_BYTES
JWT_SECRET=REPLACE_WITH_DIFFERENT_RANDOM_SECRET_AT_LEAST_32_BYTES
DEFAULT_DOMAIN=links.example.com
BASE_URL=https://links.example.com
CORS_ORIGINS=https://links.example.com
ENVIRONMENT=production
```

Use a URL-safe database password, or percent-encode it in `DATABASE_URL`.
Configure `infrastructure/Caddyfile` for your domain, or use your existing proxy.
From the repository root:

```sh
docker compose --env-file .env -f infrastructure/docker-compose.yml up --build -d
docker compose --env-file .env -f infrastructure/docker-compose.yml logs migrate worker fastapi
```

The one-shot `migrate` service runs before the API and ARQ worker start. The API
checks migration state without running DDL. `/health` returns 503 when the
database is unavailable; `/health/live` only checks that the process responds.

For a non-container PostgreSQL instance, set `DATABASE_URL` to that instance,
then run `alembic upgrade head` before `uvicorn app.main:app --reload`.
Automatic SQLite `create_all` at application startup has been removed.
Existing databases created outside Alembic need an explicit schema audit and
baseline procedure; do not blindly stamp them or apply fresh-install steps.

## Upstream reference

The [original README](docs/UPSTREAM_README.md) and existing upstream deployment
notes describe upstream functionality. They are retained for reference, not as
claims that every feature has been validated in this fork. Follow this README
and the stabilization report where they differ.
