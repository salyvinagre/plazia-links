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

## Cycle 2 - 2026-10-03
Reviewing: Wave 2 - pool rename, pool deletion, atomic selected-link deletion, V2 schema admission, and integrated browser/API behavior
Analysts: None; single independent reviewer `/root/independent_review`.

### Critical

None found.

### Warning

None found in the authorized local implementation and acceptance scope.

### Suggestion

The generated OpenAPI has zero hard errors and 184 non-error IBM style warnings. The current schemas correctly publish the bulk-delete `ids` parameter as a repeated query array bounded to 1–100 items. Before treating the contract as polished SDK documentation, consider reducing the remaining warnings for naming, examples, and field constraints.

### Spec Alignment

- The pool item contract now supports `GET`, `PATCH`, and `DELETE /api/v1/pools/{pool_id}`. Rename changes pool metadata; delete cascades to its links, subscriptions, and queued activation emails while preserving other pools.
- `DELETE /api/v1/links` accepts 1–100 explicit IDs and an optional pool filter. Canonical IDs are normalized at the boundary, duplicates are rejected, and stale, foreign, or wrong-pool selections fail before any selected row is deleted. Link deletes are audited per resource in the command transaction.
- Protected changes require idempotency keys and return original typed results on replay. Organization authority and the relevant `links:read`, `links:update`, or `links:delete` capability remain enforced through the existing API/CQRS boundaries.
- Browser controls preserve the selected pool after rename and bulk deletion. Desktop and mobile flows cover select-page, individual selection, confirmation cancellation, selected deletion, and full-pool deletion.
- V1 remains unchanged. V2 changes only the pool-to-link delete action and grants the required pool management privileges.

### Cross-Task Consistency

- New request and response schemas follow the shared `ApiRequest`/`ApiResponse` boundary. The API uses a typed query model for `ids` and preserves the versioned `ApiContract` routes and canonical identifiers.
- The private `flyway-migrate` Make recipe is shared by the guarded migration and the disposable acceptance harness. The public `make migrate` flow still performs schema preparation, Flyway migration and validation, then schema finish.
- Existing organization-reader/manager authority and the documented shared-authz registry limitation remain consistent with the accepted scope.

### Security And Operations

- Bulk deletion resolves the complete tenant- and pool-scoped selection under ordered row locks before issuing the delete; audit facts and durable mutation receipts remain within the same unit of work.
- Pool deletion relies on V2's validated composite cascade FK and the existing link-to-subscription/job cascade chain. Schema admission checks the exact source/target tables, ordered columns, delete actions, and validation state for all four edges. Native drift injections reject each dropped FK.
- The disposable V1-to-V2 acceptance fixture preserves its seeded pool and link during migration, then confirms deletion removes the link, subscription, and queued job. The harness reports empty owned-resource residue.

### Verification And Test Adequacy

- `make test`: 151 passed, 30 deselected (`output/pool-fast.log`).
- `make check CHECK_TOOL=all`: passed, including 122 formatted files, strict mypy on 95 source files, shared normalizers across 71 files, Actions/help/Markdown checks, OpenAPI with zero hard errors, and Vulture (`output/pool-checks.log`). The OpenAPI validator reports 184 style warnings.
- Final `make check`: passed; the Make/help contract retains 23 public targets and 24 pages (`output/pool-final-check.log`). `git diff --check` also passes.
- `CONTAINER_CONNECTION=plazia-root make acceptance`: actual pinned-Flyway V1 setup, populated V1-to-V2 guarded migration, cascade cleanup, then 30 native service/browser tests passed with 151 deselected and empty owned-resource residue (`output/pool-acceptance.log`).
- The acceptance suite covers both runtime modes, Chromium at 1280px and 390px, canceled confirmation with no POST, preserved pool filter, rename and deletion, and the existing API/database authorization and replay regressions. Fresh desktop/mobile screenshots were visually inspected.
- Coverage and image/package lanes were not rerun for this follow-up; prior results remain historical, as recorded in `validation.md`. CRAP was not run.

### Open Live Validation

Local disposable-service evidence does not close the external gates. Shared-authz Links-specific action/fragment publication, private package availability and GitHub workflow execution, deployed smoke, actual Identity client enrollment, restore drills, collector ingestion, and production inbox delivery remain outside this review's authorized local scope, as listed in `validation.md` and `drift.md`.

### Verdict: PASS
Reason: The reviewed Wave 2 behavior and current Flyway migration path satisfy the local API, atomicity, authorization, browser, schema, and native acceptance criteria; no critical or warning findings remain.
