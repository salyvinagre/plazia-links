# Organization link pools
Status: implemented and locally validated. Independent review and external gates are recorded in validation.md.

## Scope
The user authorized implementation and testing, organization-level ownership, a fresh Flyway schema with no customer migration, clean replacement of SQLAlchemy/Alembic, shared canonical UUIDv7 identifiers, CQRS/hexagonal boundaries and shared field normalizers. Environment prefix is PLZK_.

## Stories
- LINKS-1: An authorized organization reserves 1–100 globally unique short links in one pool; no link has a destination.
- LINKS-2: A visitor opens a reserved link and submits an email for one activation notification. Repeated normalized addresses are idempotent; no email is disclosed.
- LINKS-3: The same organization assigns a valid public HTTP(S) destination. The original URL redirects and each prior subscription queues one email atomically.
- LINKS-4: Delivery retries survive process restarts. SMTP failures never acknowledge lost work. Crash duplicates after SMTP acceptance are documented.
- LINKS-5: Cross-organization resources are invisible. Forged, expired, foreign-audience, cookie-only and replayed DPoP credentials fail closed.
- LINKS-6: Administrators use browser forms with CSRF, and operators control active organization bindings.
- LINKS-7: An authorized organization can rename a pool or delete it with all its links, subscriptions and queued notifications. Other pools remain intact.
- LINKS-8: Users inspect a pool, select several links or the current page, and delete the explicit selection atomically. Empty, duplicate, oversized, stale, foreign and wrong-pool selections fail without partial deletion. The pool filter remains selected after success.

## Acceptance
Gherkin in tests/acceptance/features/link_pools.feature binds pool/subscription/activation behavior. Additional fast API/security tests and real PG18/Redis/OpenFGA/SMTP/Chromium tests verify concurrency, RLS, commit-before-response, worker recovery and responsive forms.

Pool-management contract tests verify generated OpenAPI, required write keys,
verified-organization authority, original-result replay and canonical IDs.
Browser proof covers desktop/mobile selection, cancelled deletion, rename,
bulk deletion and whole-pool deletion in both runtime modes. A Flyway V2
migration preserves applied V1 and enables the new lifecycle.

## Boundaries
No live account provisioning, deployment or external recipient email is performed. The local issuer, disposable services and SMTP capture provide local acceptance evidence. The shared authz registry lacks a Links fragment; the organization-level adapter consumes existing reader/manager relations. Deployment alignment updates the shared PostgreSQL claim and its Flyway projection.
Production activation and worker qualification remain deferred until Identity deploys.
