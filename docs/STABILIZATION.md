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

## Verification and toolchain

The project now requires Python >=3.14 and uses uv/uv_build with a committed
`uv.lock`. The API and ARQ worker are both included in strict mypy checks.
Whole-project Ruff lint and formatting are enforced; no inherited diagnostics
are hidden with global suppressions. Existing return values now have explicit
schemas/types, including paginated collections and analytics service records.

The existing 225 unit/API tests pass on Python 3.14.7. New regression tests cover
ARQ configuration and portable hourly analytics. Opt-in PostgreSQL runtime tests
exercise a migrated PostgreSQL 18 schema, link creation/update and hour grouping.
CI runs those checks independently, alongside package and container builds.
Consult the latest PR run for the exact tested commit and results.

PostgreSQL 18 Compose volumes mount at `/var/lib/postgresql`; this is not an
in-place upgrade path for a populated PostgreSQL 16/17 volume. Read the deployment
guide before changing an existing database image.

## Remaining work before production approval

1. Repair dashboard form paths, JSON/form encoding and cookie/API authentication
   integration; add browser E2E tests. Pages returning HTML 200 are insufficient.
2. Replace the current domain-verification shortcut with actual ownership proof.
   This slice checks resource ownership but does not implement DNS verification.
3. Harden server-side URL health checks/webhooks against DNS and redirect SSRF.
   A literal-IP validator is not sufficient network egress protection.
4. Implement reliable transactional outbox/retry processing. Existing webhook
   enqueue-before-commit and delivery/retry limitations remain.
5. Expand browser E2E, PostgreSQL concurrency and migration-upgrade coverage.
   The PostgreSQL runtime smoke tests are not comprehensive load/upgrade tests.
   Audit existing non-Alembic databases before any production migration.

Then implement Identity integration and the product lifecycle: owned pools,
reserved links with no destination, confirmed visitor subscriptions, first
activation, durable notifications and non-recycled public codes. Do not use
marketing contacts as activation subscribers.

## Subsequent Identity slice

The next slice replaces the deployed authentication and core dashboard surface.
See `IDENTITY.md` for the current, explicit boundary: Identity is now the default;
legacy authentication and unfinished network-heavy management features are absent
from that profile. The inherited marketing dashboard is retained only for isolated
legacy regression work, not presented as repaired or production-approved. Pools,
subscriber verification and durable activation notifications remain separate work.
