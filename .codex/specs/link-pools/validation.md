# Validation evidence

Local closure for the organization pool cutover, 2026-10-03. No customer database, deployed application or production recipient was used.

## Evidence lanes

| Lane | Command | Evidence |
| --- | --- | --- |
| Static/types/normalizers | make check | PASS: Ruff/format 113 files, strict mypy 87 files, shared normalizers 63 files with zero findings; output/check.log |
| Fast branch coverage | make coverage | PASS: 129 tests, 88.82% branch coverage; enforced minimum 85%; output/coverage.log |
| Real-service acceptance | CONTAINER_CONNECTION=plazia-root make acceptance | PASS: 20 tests; disposable PostgreSQL 18, Redis, OpenFGA, Mailpit, Chromium and local signed OAuth issuer; output/acceptance.log |
| HTTP contract/package | make openapi openapi-check build | PASS: zero contract errors, 144 non-error validator style warnings with no rule exclusions; generated .plazia/local/openapi.json, wheel/sdist in dist/; output/artifacts.log and output/package.log |
| Production runtime | CONTAINER_CONNECTION=plazia-root make image | PASS: image fb7c12dee07e8714de6f5656bb41fb3a36c3d1da50ce7f033ea94f30e3650a88; output/image.log and output/image-inspection.log; pinned inputs and temporary source allowlist |
| Markdown/CI policy | make docs-check actions-check | PASS: output/docs.log |
| Independent review | Read-only Luna review | PASS: no critical or warning findings; [review](review.md) |

Acceptance covers first activation and precise recipient/current short URL delivery in both API deployment modes, browser sign-in/CSRF/sign-out, desktop/mobile layout, concurrent subscription/activation, tenant isolation and subscription PII separation, same-key command replay, rollback/savepoints, SKIP LOCKED competing claims, bounded retry, cancellation recovery and unsafe schema drift. The harness removes only its own labelled resources and verifies empty residue.

Thirteen security injections verify rejection of cross-role membership, table/function owner drift, weakened tenant policy, changed definer authority, subscriber-column reads, PUBLIC execution, tampered migration checksum, pool deletion/truncation privileges and worker receipt/audit reads. These guards cover critical ownership/privacy boundaries; they are not a general exact diff of every catalog property and ACL.

Final desktop/mobile captures were visually inspected. The image imports app.main/worker.run as uid 10001 on Python 3.14.8, contains templates/CSS/HTMX/Flyway SQL and omits pytest/Ruff; wheel contents were inspected separately. The production image retains its healthcheck and disables generic proxy-header rewriting. Exact proxy identity tests cover allowed, spoofed, malformed and duplicate forwarded headers.

Telemetry tests verify consumer-parent/provider-child causality, bounded private-free metrics, post-commit terminal outcomes, passive exporter failure and resolved HTTP route templates. Runtime export defaults to noop; these tests do not prove deployed collector ingestion.

Browser captures are under output/playwright: pool-container-desktop.png, pool-container-mobile.png, waiting-container-mobile.png and matching serverless captures. Generated logs, screenshots, contracts and distributions remain local ignored artifacts; source tests, migration, documentation and Make/CI lanes are reviewable repository changes.

## External gates

Shared authz Links-specific action/fragment publication is outstanding; current organization authority consumes existing Identity-owned reader/manager relations. CI requires published matching shared Python 3.14 manifests and private checkout access. GitHub workflow execution, deployed smoke, actual Identity client enrollment, restore drills, collector ingestion and production inbox delivery were not performed. The [drift disposition](drift.md) and [deployment contract](../../../docs/DEPLOYMENT.md) preserve these distinctions.

## Make conventions follow-up

The Make wrapper now delegates check selection and quality/test/coverage routes to
shared tooling through `.plazia/quality.yaml`. Default Make renders the grouped
offline help; `make check` selects the offline fast lane. Native help covers 23
public targets and 24 pages, with operational recipes suppressed for contextual
help. Tests with failing uv/Python/container stubs verified offline help and
rejection of invalid goal combinations/selectors.

`make check` and `make check CHECK_TOOL=all` pass; the broad lane retains the 144
OpenAPI style warnings and advisory semantic/wrapper findings. Focused selection
and `TEST_FLAGS` forwarding pass. Coverage now records 131 fast tests at 88.98%
branch coverage and writes ignored `coverage.crap.json`. Acceptance through the
shared test route passes 20 real-service tests with empty owned-resource residue.
Its browser interaction now opens the current row Actions menu before activation.
Evidence is in `output/makefile-{check,all,help,focused,coverage,acceptance}.log`.

The strict `CHECK_TOOL=crap` gate reads the existing report without rerunning
tests and currently fails on 35 methods above CRAP 5. This is recorded application
debt; CRAP is deferred from `hardening-checks` at the user's request and remains
available only as an explicit check.
Its report is in `output/makefile-crap.log`. The image/package evidence above
belongs to the original implementation closure.

Final requested test-only verification: `CONTAINER_CONNECTION=plazia-root make
test TEST_SUITE=all` passes 131 fast tests and 20 real-service tests, with empty
owned-resource residue. Evidence is in `output/makefile-tests.log`.

## Pool-management follow-up

Current local verification for pool rename/delete and explicit bulk link
deletion, 2026-10-03:

| Lane | Command | Result |
| --- | --- | --- |
| Fast regression | `make test` | 151 passed; `output/pool-fast.log` |
| Combined Plazia checks | `make check CHECK_TOOL=all` | PASS: Ruff/format 122 files, strict mypy 95 files, shared normalizers 71 files with zero findings, Actions/help/Markdown, generated OpenAPI with zero hard errors and 184 style warnings, Vulture, advisory semantic/wrapper diagnostics; `output/pool-checks.log` |
| Final Make/harness checks | `make check` | PASS, including the unchanged 23 public targets and 24 help pages; `output/pool-final-check.log` |
| Native database/browser | `CONTAINER_CONNECTION=plazia-root make acceptance` | Populated V1 to V2 upgrade verified, 30 passed, empty owned-resource residue; `output/pool-acceptance.log` |
| Current UI assets | `make frontend` | PASS; `output/pool-frontend.log` |
| Independent review | Read-only Luna review | Cycle 2 PASS, no critical or warning findings; [review](review.md) |

The 181 tests include original-result pool rename replay, pool cascade deletion,
explicit all-or-nothing selection, wrong-pool/foreign/stale IDs, CSRF, keys and
generated typed API schema checks. Native PostgreSQL verifies command rollback,
replay and subscription/job cleanup. Eighteen security injections include all
four deletion-chain foreign keys and pool-management grant separation.

Native acceptance creates a V1 database with the configured pinned Flyway,
seeds a pool/link/subscription/job, then runs the normal guarded `make migrate`
procedure to V2. The pool name and short code survive the upgrade; deleting the
pool removes its link, subscription and queued job. V1 is unchanged. The private
`flyway-migrate` recipe shares the configured invocation between the guarded
public migration and this harness. Runtime requires V2. This proof uses a
disposable database, with no customer data or deployed migration involved.

Real Chromium covers rename, select-page and individual selection, a cancelled
deletion that sends no POST, bulk deletion with preserved pool filter, and whole
pool deletion without affecting another pool. Both runtime modes run at 1280px
and 390px. Current desktop/mobile captures were visually inspected; selected
checkboxes use the standard primary variant and screenshot animation is
disabled for stable state evidence. Captures are
`output/playwright/pool-management-{container,serverless}-{1280,390}.png`.

All evidence above belongs to the final source. Earlier image/package and
coverage results remain historical; those lanes were not rerun for this slice.
External gates remain unchanged. CRAP was not run.

## Second-pass golden-principles audit

Current local source, 2026-10-03. Five reproducible defects failed before their
fixes: coercive JSON enabled-state input, foreign canonical-ID items in the
bulk command, inaccessible pools beyond the first 100, lost anonymous-query
request lineage, and CLI help loading runtime secret files. Evidence:
`output/second-pass-regressions.log`. Changes reuse the existing commands,
queries, normalizers and platform owners. The [SLOC decision](decisions.md)
accounts for 259 net nonblank, noncomment Python production/tooling lines and
139 test lines, including docstrings. No new business service or local parser.

| Lane | Result | Evidence |
| --- | --- | --- |
| Independent review | Terminal Cycle 3 PASS, no critical/warning findings; canonical-ID schema-pattern polish recorded as a suggestion | [review](review.md) |
| Fast branch coverage | 162 passed, 88.96%, minimum 85% enforced | output/second-pass-coverage.log |
| Broad shared checks | Ruff/format 124 files, strict mypy 96, normalizers 71, Actions/help/Markdown/env/OpenAPI/Vulture pass; no rule exclusions | output/second-pass-checks.log |
| OpenAPI | Zero errors, 104 style warnings (184 before this pass) | output/second-pass-checks.log |
| Native services/browser | Populated V1→V2 upgrade/cascade check, 30 passed, empty owned-resource residue | output/second-pass-acceptance.log |
| Frontend | Assets built; current desktop/mobile Chromium captures inspected in both modes | output/second-pass-frontend.log; output/playwright/pool-navigation-{container,serverless}-{1280,390}.png |
| Wheel/image | Built current wheel/sdist and image b385bd88db74f7ebdd49ce9fb51c926244a202d56e1eebb2f6b373a1e871e545; CLI help works with an unavailable secret file; uid 10001, Python 3.14, runtime assets and V1/V2 verified, dev tools absent | output/second-pass-package.log; output/second-pass-wheel-inspection.log; output/second-pass-image.log; output/second-pass-image-inspection.log |

The CLI uses plazia-cli command definitions; platform composition owns the
operator bus and database lifetime. Access ports and the links telemetry catalog
now occupy the mandated application drawers. Architecture tests prevent driver,
container, interface and cross-context implementation imports in the core and
prevent interface-owned runtime bus construction. Public resolve carries the
existing RequestContext. HTTP models reuse kernel canonical normalization,
bounded collections/fields, aware timestamps and strict JSON booleans.

The pure shared EnvRegistry derives declarations from Settings model metadata
without loading values. `.env.example` is regenerated by the shared tool, and
Make exposes env checks in its fast lane and help selector. Release metadata is
disabled; it does not certify a release pipeline. PLZL_ follows the explicit user
instruction even though the current portfolio prefix table assigns it to Ledger.

Four env scanner findings are false unused reports: deployment_mode,
smtp_security and telemetry_export_driver use Literal annotations, while
trusted_proxy_ips uses typed address items. The shared scanner recognizes only
primitive fields. Their runtime consumers are app.main, worker.run,
app.platform.telemetry and the rate limiter; actual deployment modes, SMTP
security and proxy behavior are covered by tests. No suppression or duplicated
aliases were added to silence these reports. Three Flyway inputs are declared
but reported as info-only unused because their Make forwarding is not scanned.

Remaining advisory semantic/wrapper findings were inspected. Redis get/getdel
have distinct consume-once behavior. CQRS handlers, context adapters, HTTP
redirect headers, settings origin guards and console entrypoints retain real
boundaries despite their short bodies. OpenAPI style debt remains in examples,
shared error/HAL metadata, generated names and IBM-specific shape conventions;
no parallel schemas or rule exclusions were added. The gherkin dependency emits
one positional-maxsplit deprecation warning. CRAP was not run.

External shared-authz publication, private artifact publication/GitHub execution,
actual Identity enrollment, deployed smoke, restore, collector ingestion and
production inbox delivery remain open. Local evidence does not replace them.
The terminal independent Cycle 3 verdict is recorded in [review](review.md).

## Pool actions and collection-wide deletion

Current local source, 2026-10-03. Pool management uses the same compact native
dropdown trigger as link rows. Rename and checkbox selection appear on demand;
cancel clears selection and restores focus. Select all means every matching
link in the selected pool or organization, across pages. Selecting all visible
rows individually does not select unseen links. All mode submits the explicit
selector instead of disabled row IDs, and its confirmation identifies the scope.

DELETE /api/v1/links retains the canonical collection path, typed query schema,
canonical IDs, verified organization context, links:delete capability, required
write key, shared command/UoW, 204 outcome and standard errors. Explicit IDs
remain bounded to 1–100; `all=true` is mutually exclusive with IDs and accepts
the same pool filter. No DELETE body or verb route was added. The repository
deletes exactly its locked set and batches the existing per-link audit facts.
Pool records remain. Retries replay success without deleting newer links.

| Lane | Current result | Evidence |
| --- | --- | --- |
| Before-fix regressions | Four default-hidden UI failures and three all-selection/authority failures reproduced | output/pool-ux-before.log; output/all-links-before.log |
| Fast coverage | 167 passed, 88.67%, minimum 85% enforced | output/pool-ux-coverage.log |
| Broad Plazia checks | Ruff/format 124 files, strict mypy 96, normalizers 71, Actions/help/Markdown/env/OpenAPI/Vulture and advisory checks pass | output/pool-ux-check.log |
| OpenAPI | Zero errors, 106 style warnings; the two new inline-schema warnings describe the optional IDs array; no exclusions or parallel schema added | output/pool-ux-check.log |
| Native services/browser | 30 passed; populated V1→V2 and cascade checks; empty owned-resource residue | output/pool-ux-acceptance.log |
| Frontend | Rebuilt assets, JavaScript syntax checked, current Chromium captures inspected | output/pool-ux-frontend.log; output/playwright/pool-menu-{container,serverless}-{1280,390}.png; output/playwright/pool-management-{container,serverless}-{1280,390}.png |

Browser proof covers keyboard activation/Tab/Escape, equal rendered trigger
dimensions, rename cancellation, selection clearing, cancelled confirmation
without POST, a 21-link pool shown over two pages, organization-wide deletion
and preserved pool navigation. Both deployment modes run at 1280px and 390px.
API proof covers 100/201-link collections; PostgreSQL deletes 98 links from a
pool and 101 across organization pools. The cases cover foreign pools/tenants,
empty pools, malformed selection modes, rollback, cascades, per-link audit
counts and replay after new links. The [source-line budget](decisions.md)
justifies 73 net production and 234 test lines using existing owners and fixtures.

These revisions postdate the terminal independent Cycle 3 review; the root
performed this slice's code review and current verification. Earlier wheel/image
evidence is historical for this revision. External acceptance gates remain open;
the browser uses a local signed OAuth issuer and disposable native services.
CRAP was not run.

## Commit preparation and external admission - 2026-10-03

Both semantic commits were tested from their staged Git trees in an isolated
sibling worktree. The runtime/CLI tree passed shared fast checks, 155 fast tests,
88.85% coverage and wheel/sdist builds (`output/local-runtime/runtime-alignment-check.log`).
The complete pool/API tree passed shared fast checks, 167 fast tests at 88.67%
coverage, 30 native service/browser tests, and wheel/sdist builds. Flyway's
populated V1-to-V2 migration and cascade checks passed; owned acceptance residue
was empty. Evidence is `output/local-runtime/pool-api-final-{check,acceptance}.log`.
OpenAPI reports zero errors and 106 style warnings
(`output/local-runtime/pool-api-final-openapi.log`). No validator rules were
excluded. The four previously traced environment scanner findings remain advisory.

Frontend regeneration reproduced the staged assets. Fresh desktop pool-menu
and mobile selection captures were inspected. The current image was built as
645119bd2621003d3e7c691fb48b1852279b69bca977db8bb3eae83efd507c2f;
runtime inspection checks Python 3.14, uid 10001, packaged templates and V1/V2
migrations, absence of development tools, and standalone CLI help with an
unavailable database secret file. Logs are
`output/local-runtime/pool-api-final-{frontend,image,image-inspection}.log`.
The [commit source budget](decisions.md) records this split. CRAP remains deferred.

GitHub run [37110690554](https://github.com/salyvinagre/plazia-links/actions/runs/37110690554)
for the previously pushed 3dbaa6a failed before product validation: both jobs
could not read private `salyvinagre/plazia` during checkout. The repository
secret inventory has no `PLZL_SHARED_SOURCE_TOKEN`; the fallback repository
token cannot read that sibling. A shared-source read credential must be
configured before GitHub acceptance can run. Local shared checkout/image proof
does not establish published package compatibility or GitHub success.

Live acceptance remains pending configuration: the current Links settings have
no Identity issuer/client, SMTP account or test inbox. The running local preview
uses the signed test issuer and Mailpit. Configuration references have been
requested for real Identity sign-in and subscription/activation inbox delivery;
these gates are not closed by the disposable-service tests above.
