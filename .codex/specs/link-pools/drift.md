# Plazia ecosystem drift and disposition

Reconciled 2026-10-03 against implemented Links and current sibling sources. The initial audit found inherited ORM/Alembic/workspace code and a Python mismatch. The table describes the current disposition. No customer data exists; the user selected a fresh schema. This task modified no sibling production sources.

Golden Principles resolve through plazia-tools principles path to ../plazia/packages/plazia-tooling. Bounded comparisons examined shared contracts and consumers in Plazia, Identity, Marketbook, Billing, TradeScale and the template, excluding environments, generated output and caches. Shared mechanisms remain distinct from service-owned domain repositories and live deployment evidence.

| Concern | Current disposition | Evidence |
| --- | --- | --- |
| Persistence | SQLAlchemy, asyncpg, SQLite and Alembic removed. Async psycopg uses shared PostgreSQL connection/pool/session contracts. Contexts own SQL repositories. | [database](../../../app/platform/database.py), [repository](../../../app/contexts/links/adapters/repositories/sql/postgres.py) |
| Migration | Pinned Flyway V1 plus applied-history-preserving V2, literal migrate/validate and read-only admission for the four cascade edges. Checks cover history checksum, RLS policies, security function bodies/search paths, owners and private grants. No fabricated history, baseline, clean or startup DDL. | [authority](../../../app/platform/persistence/schema.py), [SQL project](../../../app/platform/persistence/sql/flyway.toml), [security tests](../../../tests/integration/test_schema_security.py) |
| Python | Current Links/shared manifests overlap at >=3.14,<3.16. The original 3.13 recommendation is superseded. Shared manifests changed concurrently outside this task; Links retains their verified current 3.14 contract. | [manifest](../../../pyproject.toml), [lock](../../../uv.lock) |
| IDs | Shared Identity OrganizationId replaces the bespoke type. Links registers lnk/lpl/lsb CanonicalIds with UUIDv7; PostgreSQL stores UUID scalars. A bounded current scan found no collision; pol was already TradeScale-owned. | [IDs](../../../app/kernel/ids.py) |
| Hexagonal CQRS | Intent commands/queries, driver-free application/domain, ports, context adapters, shared messaging buses/UoW and dependency-injector composition. Superseded services/workspaces/marketing paths removed. | [composition](../../../app/platform/composition.py), [boundaries](../../../tests/architecture/test_context_boundaries.py) |
| Normalization/context | Shared AnnotatedFields normalizers, normalized email, canonical IDs, RequestContext/ActorContext/OperationContext and bounded TraceContext. Tenant selector is plazia.organization_id. | [domain](../../../app/contexts/links/domain/link.py), [dispatch](../../../app/interfaces/dispatch.py) |
| HTTP | /api/v1 audience/routes; shared envelopes, HAL and forward tokens. Required mutation keys replay typed original results. Receipts/state/audit/jobs share the transaction. | [API contract](../../../app/kernel/api.py), [routes](../../../app/interfaces/api/links.py), [replay](../../../tests/integration/test_command_replay.py) |
| Notifications | Shared SMTP transport. Links owns wording/subscriptions/jobs; separate worker role, same-row activation locks, SKIP LOCKED, five attempts, retention and at-least-once crash duplicates. | [workflow](../../../app/contexts/links/application/workflows/notifications.py), [queue](../../../app/contexts/links/adapters/repositories/sql/notifications.py) |
| Configuration/tooling | Shared settings sources, PLZL_ selectors, guarded secret files and non-secret TOML. Pure shared EnvRegistry declarations generate .env.example; Make/shared env/normalizer/OpenAPI/docs/Actions lanes. Operator intents use plazia-cli with runtime-owned CQRS composition. Locked image build materializes a source allowlist. | [settings](../../../app/platform/settings.py), [Make](../../../Makefile), [image](../../../tools/image.py) |
| Telemetry | Shared HTTP/runtime export lifecycle, bounded queue signals, W3C durable handoff and passive failures. No recipient/tenant metric dimensions. | [runtime](../../../app/platform/telemetry.py), [signals](../../../app/contexts/links/application/telemetry/signals.py), [tests](../../../tests/unit/test_telemetry.py) |

## Retained protocol boundary

Identity's adopted OAuth access-token profile uses RFC 9068 fields and client capabilities. Shared authlib's session verifier expects uid/sid/ver/env fields. Direct substitution changes the consumer contract. Links retains PyJWT/OAuthlib profile adapters while adopting shared IDs, authorization subjects, settings, messaging, HTTP contracts and SMTP transport. See the [Identity contract](../../../docs/IDENTITY.md).

## Remaining gates

The shared authz registry has no Links action/fragment packet. Links checks token capabilities and existing Identity-owned organization reader/manager relations through the official SDK. It never writes membership tuples or impersonates another product's actions. Product-specific registry publication belongs to the shared package/model owner.

CI needs matching published shared 3.14 manifests and read access to its private sibling checkout. Local resolution/image builds do not prove publication or a successful GitHub run. Real Identity enrollment, deployed smoke, collector ingestion, restore drills and production inbox delivery remain live gates. Serverless needs a separate persistent worker. See [validation evidence](validation.md) for exact local closure.
