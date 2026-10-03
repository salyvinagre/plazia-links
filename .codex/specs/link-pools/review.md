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

## Cycle 3 - 2026-10-03
Reviewing: Wave 3 - second-pass regression fixes, environment/CLI/architecture alignment, SLOC justification and integrated implementation against `f569415`
Analysts: None; terminal independent reviewer `/root/independent_review`.

### Critical

None found.

### Warning

None found in the reviewed local implementation and acceptance scope.

### Suggestion

The generated OpenAPI has zero hard errors and 104 non-error style warnings, down from 184 in the prior pool-management pass. In particular, runtime ID validators enforce the canonical prefix and UUIDv7 shape while generated schemas primarily publish length bounds. A future shared-kernel schema hook could expose that format to clients without duplicating its UUID rules in this route layer. The checked-in schemas remain typed and the server rejects malformed IDs, so this is contract polish rather than a runtime correctness issue.

### Spec And Golden-Principles Alignment

- The five failures recorded in `output/second-pass-regressions.log` were reproducible before their fixes: coercive JSON booleans, accepting a foreign canonical-ID type in bulk deletion, inaccessible pools beyond the first 100, lost request context for anonymous public resolution, and CLI help loading runtime secrets. Each fix extends its existing schema, command, query context, browser navigation, CLI or platform owner; no parallel service or parser was added.
- The API reuses `ApiRequest`/`ApiResponse`, Pydantic query models, canonical identifier normalizers, versioned `/api/v1` routes, explicit bounded selection, verified organization capabilities and required mutation keys. Mutation paths preserve the existing typed replay and owner transaction boundary. Request schemas reject unknown fields; public times are timezone-aware.
- Operator commands use shared `plazia-cli` command definitions. Owner bus construction and database lifetime remain in platform composition, while CLI help constructs neither settings nor database connections. The documentation correctly scopes the owner DSN to operator commands.
- The environment registry is a pure declaration built from existing settings metadata and the shared `EnvRegistry`; it does not load secrets or implement a local settings parser. `.env.example` is generated from it. `PLZL_` follows the explicit user choice despite the sibling prefix table, and the pre-existing native `FLYWAY_*` inputs remain confined to the pinned Flyway process. The disabled preview release declaration does not claim release readiness.
- Application ports and telemetry signals now occupy their required drawers. Architecture tests enforce context ownership, framework/storage-free application cores, and runtime-owned bus composition. The exact SLOC deltas were independently reproduced: app/worker +148, tooling +111, tests +139. The justification in `decisions.md` ties those additions to the shared registry, CLI ownership, contract constraints, browser navigation and regression/architecture evidence; telemetry relocation is net zero.
- Four environment scanner findings are explained by current `Literal` or typed-IP settings annotations and their traced runtime consumers. The three Flyway zero-use notes are due to Make forwarding to the separate CLI process. Neither is suppressed or hidden by duplicate aliases. The Redis `get`/`take` duplication has distinct consume-once semantics; short wrapper candidates retain their adapter, transport or runtime boundary.

### Verification And Evidence Limits

- `output/second-pass-coverage.log`: 162 tests passed at 88.96% branch coverage, above the 85% gate.
- `output/second-pass-checks.log` and `output/second-pass-final-check.log`: formatting/Ruff, strict typing, shared normalizers, Actions, Make help, environment audit and documentation checks pass. OpenAPI has zero hard errors and 104 style warnings; no validator rules are excluded. The shared semantic/wrapper and dependency deprecation notices are advisory and documented above.
- `output/second-pass-acceptance.log`: the configured pinned Flyway migrated a populated V1 database through the guarded V2 path, preserved the fixture and verified cascade cleanup; 30 native service/browser tests passed and the owned-resource residue check was empty.
- Current Chromium coverage includes navigation beyond 100 pools and rename/delete flows in container and serverless modes at 1280px and 390px. The fresh captures under `output/playwright/pool-navigation-{container,serverless}-{1280,390}.png` were visually inspected.
- Current wheel/image checks passed. The image inspection verifies Python 3.14.8, uid 10001, required runtime assets, V1/V2 migration files, CLI help with unavailable secret files, and absence of development tools (`output/second-pass-image-inspection.log`; image hash recorded in `validation.md`). `uv.lock --check --offline` passes. CRAP remains deferred as instructed.
- Shared-authz Links action/fragment publication, private package publication and GitHub workflow execution, actual Identity enrollment, deployed smoke, restore drills, collector ingestion and production inbox delivery remain external gates. Local disposable services and screenshots do not substitute for them; `validation.md` and `drift.md` retain these limits.

### Verdict: PASS
Reason: The reviewed regressions are closed through existing owners, architecture and environment boundaries follow the applicable shared principles, all new SLOC is justified, and current fast, broad, native-service, browser, packaging and image evidence passes. No critical or warning findings remain within the authorized local scope; the OpenAPI style suggestion and external gates above are non-blocking and explicitly bounded.
