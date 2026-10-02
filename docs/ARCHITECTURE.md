# Architecture

Plazia Links is a single FastAPI service with a Python worker and extraction-ready
contexts. The inherited Zly modules are a migration boundary, not an excuse to
put new business logic into transport handlers or SQL adapters. The historical
upstream description is kept in [upstream/ARCHITECTURE.md](upstream/ARCHITECTURE.md).

This layout applies the portfolio's [layer rules](https://github.com/salyvinagre/plazia/blob/main/docs/golden-principles/architecture/LAYERS.md)
and [runtime-composition rules](https://github.com/salyvinagre/plazia/blob/main/docs/golden-principles/architecture/runtime-composition.md).

## Dependency direction

```text
HTTP/CLI interfaces → platform composition → contexts
                                           ├── domain
                                           ├── application → domain + owned ports
                                           └── adapters → application/domain
```

`app/api`, `app/routes`, `app/schemas`, `app/core/identity.py` and `app/cli.py`
are delivery adapters in the inherited directory layout. The new Identity/link
surface imports context contracts and stable platform factories, never concrete
context repositories or browser protocol implementations. No duplicate runtime
container is constructed inside an endpoint.

Each context publishes `contracts.py`. Cross-context imports use that module
only. Domain and application modules are independent of FastAPI, Pydantic,
SQLAlchemy, HTTPX, OAuthlib, JWT/Redis implementations and process settings.
The import-boundary tests load the core with Python's site-packages disabled.

## Access ownership

| Concern | Placement |
| --- | --- |
| Verified principal, permissions, browser session and canonical organization ID | `contexts/access/domain` |
| Sign-in/session lifetime policy and one-use attempts | `contexts/access/application/browser.py` |
| Active binding resolution and bind/disable organization commands | `contexts/access/application/workspaces.py` |
| Token, proof, authorization-code, browser-state and binding ports | `contexts/access/application/ports.py` |
| OIDC HTTP exchange, JWT/DPoP verification, serialization, Redis and SQL | `contexts/access/adapters` |
| Local binding table definition | `contexts/access/adapters/models.py` |

The browser application service receives an authorization-code client, token
verifier and typed state-store port. OIDC requests and JSON encoding are adapter
work; session lifetime and browser-client policy are application work. SQL reads
return `WorkspaceBinding`/`WorkspaceView`, not an ORM instance. Provisioning
idempotence and forbidden reassignment are application decisions.

No credential replica or implicit email-based ownership is introduced. Crypto
and protocol libraries remain reusable adapters; the domain does not implement
JWT signature algorithms or an HTTP client.

## Link ownership

`contexts/links/domain/link.py` owns destination/code validation and immutable
creation/update commands. A caller cannot bypass those invariants by skipping
Pydantic HTTP validation. Destination validation is lexical; it does not resolve
DNS or make an outbound HTTP request and is not a general-purpose SSRF defence.

`LinkManagement` checks permissions and resolves the active workspace on each
operation through the published access contract. It owns allocation/retry policy
and write/audit orchestration. Every repository method receives an explicit bound
workspace ID; there is no unscoped method hidden behind a scoped interface.

`SqlLinkRepository` owns SQL translation, persisted rows, scoped lookup and
mapping database conflicts to application errors. It no longer calls an HTTP
schema or the legacy `link_service`. Only a short-code uniqueness collision is
translated to `LinkConflictError`; unrelated integrity failures propagate. A
savepoint keeps the outer request transaction usable after an expected collision.
`SqlLinkAudit` shares that transaction. A failed audit aborts the outer command;
it is not an independent commit or a notification outbox.

Management routes and public redirects use function-scoped database dependencies.
Commit/rollback therefore finishes before any HTTP success or redirect is sent.
A failed commit returns an error rather than a false success; a browser following
a write redirect cannot race an uncommitted update on a different connection.
Transport-level regression tests observe ASGI response start and deliberately
delay/fail the commit to verify this ordering for both JSON and HTML mutations.

Commands, read models and ports are separate modules. JSON and HTML adapters
shape their own transport responses from the same application results. SQL
rows, HTTP response models and externally mutable dictionaries are not domain
entities.

## Composition and deployment

`app/platform/access.py` constructs access implementations and the authorized
link-management service. Its factories bind ports; they do not decide who may
access a workspace. `app/platform/links.py` binds click execution to the selected
deployment. `app/platform/database.py` controls connection lifetimes. Settings
remain centralized in the existing runtime-owned `app/config.py`.

Both `app.main:app` and the native function entrypoint `app.index:app` expose the
same application. `api/index.py` is a thin ASGI export for existing tooling, not
a second app or `sys.path` mutation. Deployment selection changes runtime
bindings, not the domain or use cases.

| Profile | Database binding | Click binding |
| --- | --- | --- |
| `container` | Async SQLAlchemy engine with pre-ping | ARQ queue with synchronous fallback |
| `serverless` | Async SQLAlchemy `NullPool` | Synchronous persistence inside the request |

Authentication state is always external Redis, including atomic replay/one-use
operations. PostgreSQL migrations are an explicit deployment command; startup
only checks the revision. The Vercel build preflight checks configuration and
assets without connecting to a database or creating tenant data.

## Explicit legacy boundary

Existing link, workspace, audit and analytics table definitions remain in
`app/models` while the adopted core is extracted incrementally. The existing
`app/models/__init__.py` is also the Alembic/test metadata-registration bridge;
it imports the new context-owned binding model once. It contains no policy.

The click adapter deliberately reuses the inherited click persistence service.
That bridge stays in `contexts/links/adapters/clicks.py`; it is not imported by
application/domain code. Moving every inherited ORM model or service is not
part of this review. The restricted Identity profile does not expose the legacy
marketing/admin authentication or unsafe generic outbound APIs.

## Executable checks

- `tests/architecture`: core imports, cross-context contracts and delivery boundaries.
- `tests/unit`: application policy against ports and direct domain validation.
- `tests/acceptance`: signed tokens and HTTP security boundaries.
- `tests/test_postgres_runtime.py`: migrated PostgreSQL, scoped operations,
  collision recovery and write/audit rollback.
- `tests/e2e`: actual browser flow through both deployment profiles with PostgreSQL
  and Redis; the issuer is a controlled test service, not live Plazia Identity.
- `tests/unit/test_serverless_profile.py`: read-only preflight, TLS configuration,
  ASGI export, bundle inputs, connection lifetime and inline click binding.

Do not weaken the import tests by blanket exclusions when adding a new context.
Add a published contract or move the dependency to its actual owning adapter.
