# First stabilization slice

This is a bounded maintenance change on top of merge `f8600f44b28901ab9b095d3648c06fdca8fd53c7`.
It is not completion of the Plazia Links product or a blanket security approval.

## Changes

- Join both upstream Alembic heads without rewriting their ancestry. Correct
  the invalid historical SQL default for a fresh database, then add a forward
  migration for missing model columns, indexes and the audit table.
- Remove startup schema mutation. Refuse an unapplied or ambiguous schema;
  run migrations as a separate deployment step.
- Install the source before building the container package; run as a non-root
  user. Include the previously missing ARQ worker and valid ARQ cron objects.
- Check API-key workspace and scope restrictions before the owner's shortcut.
  Preserve the existing unrestricted-key behavior only inside its own workspace.
- Enforce ownership of nested domain resources and target folders.
- Reject unrecognized redirect hosts and cross-workspace codes on verified
  custom domains. Codes remain globally unique; per-domain duplicate codes
  are not introduced by this change.
- Temporarily remove the naked redirect-URL cache. Its fast path bypassed state,
  password, archive and tracking logic, and invalidation used another key prefix.
  Redis remains in use for jobs and other existing caches. A policy-aware cache
  may be reintroduced only with invalidation and authorization regression tests.
- Serialize webhooks without modifying the ORM signing secret. Specialize link
  and click pagination schemas; accept/persist link notes during creation.
- Repair the missing Request import that prevented the application from loading.

## Local verification

On Python 3.13.5, the collected suite was run in three non-overlapping batches:
68 API tests, 62 API tests and 95 remaining tests: **225 passed**. This includes
15 new regression tests for migration-head shape, read-only startup checks,
API-key boundaries, folder/domain ownership, non-mutating serialization,
typed pagination and redirect namespace/cache behavior.

Only project pytest plugins were loaded. The unit database was SQLite, and
Redis/network boundaries were mocked where the existing fixtures do so.
These results do not establish live PostgreSQL behavior, browser E2E behavior,
load limits or exactly-once message delivery.

Ruff passes on the changed/new Python files. Full-project Ruff and mypy retain
upstream debt; CI deliberately continues to report it. PostgreSQL offline DDL
rendering succeeds. The separate real PostgreSQL CI job is the authority for
fresh migration execution and model/schema drift; inspect the PR's latest run.

## Remaining work before production approval

1. Repair dashboard form paths, JSON/form encoding and cookie/API authentication
   integration; add browser E2E tests. Pages returning HTML 200 are insufficient.
2. Replace the current domain-verification shortcut with actual ownership proof.
   This slice checks resource ownership but does not implement DNS verification.
3. Harden server-side URL health checks/webhooks against DNS and redirect SSRF.
   A literal-IP validator is not sufficient network egress protection.
4. Implement reliable transactional outbox/retry processing. Existing webhook
   enqueue-before-commit and delivery/retry limitations remain.
5. Resolve inherited full-project lint/type debt, pin dependencies and adopt uv
   tooling. Do not claim a locked or Python 3.14-validated environment yet.
6. Add PostgreSQL application integration, concurrency and migration-upgrade
   tests beyond the fresh-database migration job. Audit existing non-Alembic
   databases before any production migration.

Then implement Identity integration and the product lifecycle: owned pools,
reserved links with no destination, confirmed visitor subscriptions, first
activation, durable notifications and non-recycled public codes. Do not use
marketing contacts as activation subscribers.
