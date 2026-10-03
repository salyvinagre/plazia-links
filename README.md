# Plazia Links

Reserve organization-owned short links, share them before a destination exists, and notify subscribers when the owner activates them.

Requires Python 3.14, uv 0.12.21, PostgreSQL 18, Redis, an Identity OAuth client and the portfolio OpenFGA organization model. Shared Python packages are consumed from the sibling plazia/packages checkout. Copy .env.example and supply the Identity, OpenFGA and SMTP configuration; all application selectors start with PLZL_.

```sh
uv tool run --from uv==0.12.21 uv sync --locked
make check
make test
make coverage
make acceptance
```

`make` or `make help` shows the grouped target index without requiring uv,
Python or service configuration. `make <target> help` shows guidance without
running that target; for example, `make check help CHECK_TOOL=normalizers`.

`make check` defaults to the offline `fast` lane: lint, formatting, types,
normalizers, environment declarations, Actions and Make-help policy, and Markdown links. Select a shared tool with
`make check CHECK_TOOL=links CHECK_FLAGS='README.md'`, or use `CHECK_TOOL=all`
for the broader diagnostics, including freshly generated OpenAPI validation.
Checks and suites are declared in `.plazia/quality.yaml`. `make test` accepts
`TEST_SUITE=fast|unit|architecture|integration|acceptance|all` and forwards
pytest arguments with `TEST_FLAGS='-k pagination'`. Flags apply to direct pytest
steps; the acceptance harness runs its fixed suite. The integration suite
requires configured test services; acceptance provisions its own disposable services.
`make preflight` runs the fast checks and one fast test pass within 285 seconds.
`make hardening-checks` collects coverage once, then runs the broader diagnostics;
CRAP is currently deferred from this combined gate. Coverage supports the `fast` suite and writes the ignored
`coverage.crap.json` report; `CHECK_TOOL=crap` reads that report without running tests.

The acceptance lane creates isolated local PostgreSQL, Redis, OpenFGA and Mailpit containers, migrates with pinned Flyway, exercises real Chromium and removes its test resources. It uses a local signed OAuth fixture. It does not establish live Identity provisioning or production inbox delivery.

Start the API with uv run uvicorn app.main:app --port 8000 and the persistent worker with uv run python -m worker.run. /login opens the organization management interface. Reserve 1–100 links, share a public URL, then use Activate to assign a valid HTTP(S) destination. Visitors receive one activation email for that link.

Choose a pool to inspect its links, rename it, or delete the pool and all its
links. Select individual checkboxes or “Select this page”, then use “Delete
selected” to remove several links together. Deletion also removes their
subscriptions and queued notifications; other pools and unselected links remain.

The interface uses server-rendered Jinja templates, HTMX, Tailwind CSS and daisyUI.
Its assets follow the [daisyUI Django installation approach](https://daisyui.com/docs/install/django/):
the standalone Tailwind executable compiles local daisyUI bundles, without Node.js or npm.
Run `make frontend` after editing templates or `app/static/css/identity.source.css`.
The CSS entry point imports `theme.css` for brand tokens, `base.css` for typography
and shared helpers, and `links.css` for the responsive table. Use daisyUI components
and Tailwind utilities in templates for ordinary layout; keep custom CSS in these
focused files rather than overriding every component.
The build downloads pinned, checksum-verified assets into `.cache/ui`, reuses them on
subsequent builds, and writes the CSS and HTMX script under `app/static`. These compiled
files ship with the Python application. The Plazia theme and Links logo follow the
Company brand book, edition 1.3; see `app/static/brand/README.md` for asset provenance.

| API | Capability |
| --- | --- |
| POST /api/v1/pools | links:create |
| GET /api/v1/pools | links:read |
| GET /api/v1/pools/{pool_id} | links:read |
| PATCH /api/v1/pools/{pool_id} | links:update |
| DELETE /api/v1/pools/{pool_id} | links:delete |
| GET /api/v1/links?pool_id=lpl_… | links:read |
| POST /api/v1/links | links:create |
| GET /api/v1/links/{link_id} | links:read |
| PATCH /api/v1/links/{link_id} | links:update |
| DELETE /api/v1/links/{link_id} | links:delete |
| DELETE /api/v1/links?ids=lnk_…&ids=lnk_… | links:delete |

Each management request also requires OpenFGA organization authority and an active local binding. Pool ownership comes exclusively from the verified org claim. Pool creation returns its id, name and size; its Location header identifies the canonical pool read. List its links with the pool_id filter. PATCH destination_url activates a reserved link. POST /{code}/subscriptions accepts a form email. Disabled links return 410, unknown links 404, reserved links a waiting page, and active links 307.

Pool PATCH accepts only `{"name": "Upcoming launch"}`; `null` clears the name.
Bulk DELETE accepts 1–100 distinct `ids` query values and an optional `pool_id`
restriction. Any missing, foreign or mismatched link produces 404 without
deleting the other selected links. Successful deletion returns 204. Invalid
selections return 422; changed idempotency payloads return 409. Generated
`/openapi.json` is the authoritative typed request/response contract.

Every protected POST, PATCH and DELETE requires an `Idempotency-Key` of 1–128 ASCII letters, digits or `-_.:`. Retry the same operation with the same key and payload to receive its original result, with `Idempotency-Replayed: true`. A changed payload conflicts with 409. Receipts, state, audit and activation jobs commit together; failed commands leave no receipt. Authority and the active organization binding are checked again on replay. Browser forms carry their own hidden keys.

Collections accept `limit` (1–100), an opaque `token` and the optional link `pool_id` filter. Follow their shared HAL `self`, `first` and `next` links. Tokens bind the caller, organization, issuer, filter and limit. Navigation uses bounded offsets; concurrent inserts/deletes can move page contents. The OAuth resource audience is the canonical HTTPS `/api/v1` base.

This is a fresh-schema cutover: no customer-data upgrade is supported. Removed inherited marketing/authentication/workspace routes have no compatibility mode. See [architecture](docs/ARCHITECTURE.md), [configuration and deployment](docs/DEPLOYMENT.md), [Identity contract](docs/IDENTITY.md), [implementation packet](.codex/specs/link-pools/spec.md), and [validation evidence](.codex/specs/link-pools/validation.md).
