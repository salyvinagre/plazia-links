# Organization link pools
Status: implemented and locally validated. Independent review and external gates are recorded in validation.md.

## Scope
The user authorized implementation and testing, organization-level ownership, a fresh Flyway schema with no customer migration, clean replacement of SQLAlchemy/Alembic, shared canonical UUIDv7 identifiers, CQRS/hexagonal boundaries and shared field normalizers. Environment prefix is PLZL_.

## Stories
- LINKS-1: An authorized organization reserves 1–100 globally unique short links in one pool; no link has a destination.
- LINKS-2: A visitor opens a reserved link and submits an email for one activation notification. Repeated normalized addresses are idempotent; no email is disclosed.
- LINKS-3: The same organization assigns a valid public HTTP(S) destination. The original URL redirects and each prior subscription queues one email atomically.
- LINKS-4: Delivery retries survive process restarts. SMTP failures never acknowledge lost work. Crash duplicates after SMTP acceptance are documented.
- LINKS-5: Cross-organization resources are invisible. Forged, expired, foreign-audience, cookie-only and replayed DPoP credentials fail closed.
- LINKS-6: Administrators use browser forms with CSRF, and operators control active organization bindings.

## Acceptance
Gherkin in tests/acceptance/features/link_pools.feature binds pool/subscription/activation behavior. Additional fast API/security tests and real PG18/Redis/OpenFGA/SMTP/Chromium tests verify concurrency, RLS, commit-before-response, worker recovery and responsive forms.

## Boundaries
No live account provisioning, deployment or external recipient email is performed. The local issuer, disposable services and SMTP capture provide local acceptance evidence. The shared authz registry lacks a Links fragment; the organization-level adapter consumes existing reader/manager relations. No sibling production files are modified.
