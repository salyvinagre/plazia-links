## Cycle 1 - 2026-10-03

### Critical

None found in the reviewed implementation.

### Warning

None found within the authorized local cutover scope.

### Suggestion

`output/artifacts.log` reports zero OpenAPI hard errors and 144 IBM style warnings. Before presenting this generated contract as polished SDK-consumer documentation, reduce the warnings for descriptions, constraints, examples, naming, and PATCH media types. This is contract-quality debt, not a blocking validity error.

### Spec Alignment

- The implementation follows the requested clean break: current runtime and persistence code use Psycopg, the versioned Flyway SQL migration owns schema creation, and SQLAlchemy/Alembic are removed. The manifest targets Python 3.14 and uses the shared Plazia packages. See `pyproject.toml`, `app/platform/persistence/sql/migrations/V1__link_pools.sql`, and `app/platform/persistence/schema.py`.
- Shared canonical ID/value-object and normalizer boundaries are used for organizations, links, pools, public codes, destinations, and subscription email. Public API resource IDs are canonical; PostgreSQL stores UUID values. The `make check` normalizer lane passes.
- The public contract is based at the canonical HTTPS `/api/v1` audience and route base. `ApiContract` owns that base; deployment validation rejects a noncanonical audience. Request and response schemas use `shared_http.fastapi.ApiRequest` and `ApiResponse`.
- The owner-owned pool flow and subscriber activation lifecycle are represented as commands/queries and repository operations. Protected mutation replay is keyed and snapshotted within the scoped database transaction alongside its state, audit, and notification intent. Subscription and activation serialize on the link; notification claims use row locking, bounded retries, and cancellation recovery. The real-service acceptance lane exercises these cases.
- The implementation keeps the known shared-authz boundary explicit: the organization authority uses the existing Identity-owned `reader`/`manager` relations through the official SDK, while Links-specific action/fragment publication remains external work. This is documented in the specification and deployment notes, rather than hidden as a local authority replica.

### Cross-Task Consistency

- Runtime settings and deployment examples use the `PLZL_` namespace. The separate owner DSN is confined to the documented schema-provisioning operation; API and worker startup require their dedicated runtime roles.
- Container and serverless API modes share the API contract, identity audience, and application behavior. The API and worker use distinct database identities. No legacy SQLAlchemy/Alembic path or compatibility migration is retained, consistent with the authorized clean break.
- Shared package source and Python-version constraints align locally. CI still depends on published matching Python 3.14 package manifests and private package checkout access; provider execution is listed under external validation.

### Security And Operations

- Identity validation checks issuer, audience, token type, scope, normalized organization, and DPoP binding where present. Organization authority and the normalized token organization are checked before protected work; database scope is transaction-local and tenant tables enforce RLS.
- Flyway remains the schema authority. Runtime schema admission verifies the packaged migration checksum/history, expected tables, RLS policies, security-function definitions, ownership, runtime role separation, and selected critical effective privileges. `tests/integration/test_schema_security.py` injects real PostgreSQL drift for policies, functions, ownership, grants, role membership, and migration history. The guard is intentionally a critical-boundary check, not a full exact ACL diff for every possible database role.
- Forwarded rate-limit identity is accepted only from configured immediate proxy addresses; the image disables native Uvicorn proxy-header rewriting. The supplied Compose topology does not silently add a proxy trust boundary.
- Notification delivery is durable and at-least-once across the SMTP acknowledgement/commit crash window; retries and cancellation preserve recoverable work. The docs state this delivery boundary. Telemetry export is bounded and failure-isolated, and durable jobs carry bounded W3C context.

### Verification And Test Adequacy

- `output/coverage.log`: 129 fast tests passed at 88.82% branch coverage, above the 85% gate.
- `output/acceptance.log`: 20 real-service acceptance tests passed against disposable PostgreSQL 18, Redis, OpenFGA, Mailpit, and Chromium with a local signed OAuth issuer; Flyway migrate/validate and schema-finish passed, and the harness verified empty resource residue. This includes both API deployment modes, browser flows, exact SMTP recipient/current short URL, concurrent activation/subscription, tenant isolation, replay, retry, cancellation, and schema-drift rejection.
- `output/check.log`: Ruff, formatting, mypy, and shared normalizer checks passed. The saved packaging and production-image lanes also passed.
- `output/artifacts.log`: OpenAPI validation has zero hard errors and 144 style warnings, recorded above.
- At the review snapshot, `output/docs.log` showed `docs-check` failing only because this referenced `review.md` had not yet been created. Rerun `make docs-check` after adding this file before treating the documentation lane as closed; no other failure is recorded in that log.

### Open Live Validation

Local disposable-service evidence is not live acceptance. The following external evidence remains outside this review and is explicitly recorded in `validation.md` and `drift.md`: publish and enroll the matching shared-authz Links contract; execute the GitHub workflow with its private package access; verify deployment smoke and actual Identity client enrollment; exercise restore drills; verify collector ingestion; and confirm delivery to a production inbox. No customer database or production recipient was used.

### Verdict

PASS for the authorized local implementation and real-service acceptance scope. No in-scope critical or warning findings remain. External publication and deployment evidence remains open as listed above; the documentation link check must be rerun after this file is added.
