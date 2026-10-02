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
