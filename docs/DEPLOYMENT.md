# Configuration and deployment

Links owns `PLZK_`; Ledger owns `PLZL_`. This is a clean break: Links does not
read its former selectors or host-path aliases. The generated
[environment example](../.env.example) comes from the pure
[EnvRegistry](../tools/environment.py). Use `make env-example` to regenerate it
and `make check CHECK_TOOL=env` to audit the declarations.

The shared `RuntimeSettingsSources` reads explicit constructor input, guarded
`NAME`/`NAME_FILE` secrets, non-secret process overrides, resolved TOML, optional
root `.env`, and mounted secret files in that order. `.env` loads only for local
Python execution; containers receive selected files. Secrets are forbidden in
all TOML sections, including sections owned by another process. Runtime code
never merges configuration layers.

The [release declaration](../.plazia/delivery.yaml) lists `runtime.toml` then the
selected preview/production policy's TOML under [ops/containers/config](../ops/containers/config/).
Shared tooling merges these layers and projects one protected file through
`PLZK_CONFIG_FILE`. `PLZK_CONFIG` is the declaration's base selector. Runtime
sections are `[app]`, `[identity]`, and `[worker]`.

Credential ownership is explicit:

| Process | Secret selectors |
| --- | --- |
| API | `PLZK_DATABASE_URL`, `PLZK_REDIS_URL`, `PLZK_OPENFGA_STORE_ID`, `PLZK_OPENFGA_MODEL_ID`, `PLZK_IDENTITY_CLIENT_SECRET` |
| Worker | `PLZK_WORKER_DATABASE_URL`, optional `PLZK_WORKER_SMTP_PASSWORD` |
| Owner CLI and prepare/finish jobs | `PLZK_SCHEMA_DATABASE_URL` |
| Flyway job | `PLZK_FLYWAY_USER_TOML` |

All listed selectors accept `_FILE`. Compose binds them per service; it never
mounts owner credentials into the API or worker. The worker reads the public
origin through `PublicSettings` without loading confidential OAuth settings.
Owner commands no longer reuse the API database selector. The API and worker
reject an absent runtime DSN. Secret fields are excluded from settings dumps
and representations.

PostgreSQL 18 is provisioned through the root PostgreSQL capability's `links`
claim, owned by `salyvinagre/plazia-links`. It issues separate schema, API and
worker credentials for each retained environment. `links_owner`, `links_app`
and `links_worker` are semantic keys; their physical role names are provider
outputs. Schema admission resolves them through shared `PostgresRoles` and
rejects an absent or foreign-owner database marker. Runtime roles must not be
superuser, BYPASSRLS, CREATEDB, CREATEROLE, replication or inheriting roles,
and cannot join the owner/the other runtime role. The API cannot
provision organization bindings or read subscription PII. Identity owns
Identity/OpenFGA memberships independently of Links' local activation binding.

## Fresh schema
Set PLZK_SCHEMA_DATABASE_URL to the owner DSN for this command only and
PLZK_FLYWAY_USER_TOML_FILE to the private provider-generated Flyway document.
Native migrations and shared releases use the same credential/placeholder
projection. The pinned Flyway container receives that document and a read-only
SQL project mount. Native role placeholders plus declared appRole/workerRole
aliases keep V1/V2 SQL and their checksums unchanged.

```sh
make migrate
make schema-check
uv run python -m app.cli bind-organization org_0199a112345670008000000000000001 --name "Example organization"
```

make migrate runs read-only admission, literal Flyway migrate (with validation on migrate), Flyway validate, then read-only catalog verification. Startup compares the packaged migration checksum, security-function bodies/search paths/definer flags, tenant policy expressions, object owners and sensitive runtime grants. Manual security drift is rejected; startup never repairs it. The checksum follows the [Flyway source algorithm](https://github.com/flyway/flyway/blob/flyway-13.4.0/flyway-core/src/main/java/org/flywaydb/core/internal/resolver/ChecksumCalculator.java). Flyway baseline/clean are disabled. Startup never migrates or accepts an unversioned legacy database. There is no customer-data conversion path. Do not change applied migrations; add a new version for later changes.

Operator commands use the shared plazia-cli parser; `uv run --locked plazia-links --help` works without runtime secrets or network access. Owner CQRS assembly and database lifetime live in platform composition. Only an owner credential can bind/disable organizations. Supply PLZK_IDENTITY_ISSUER and PLZK_SCHEMA_DATABASE_URL to the operator command; never run the API with that credential. disable-organization revokes existing management sessions on their next request without affecting public destinations.

Pool management requires Flyway V2. Run the same owner-scoped `make migrate`
before starting this application revision against a V1 database. Admission
accepts verified V1 history for upgrade; runtime refuses an unmigrated V1
database. V2 adds pool UPDATE/DELETE privileges for the API role and cascades
pool deletion to links. The worker retains no pool-management access. No
conversion from inherited ORM storage is provided.
Admission verifies all four deletion-chain foreign keys, including their tables,
ordered tenant columns, cascade actions and validation state, so dropped or
altered constraints cannot silently leave subscriptions or queued mail behind.

## Runtime
Container entrypoint: app.main:app. Serverless ASGI entrypoint: app.index:app; database scopes open per invocation, while container mode uses a lazy shared PostgreSQL pool. Both require Redis and OpenFGA. /health is startup readiness evidence, not ongoing SMTP or provider health. Vercel requires the same shared dependency artifacts in its build context; the sibling editable-source development checkout alone is not a self-contained cloud upload.

Run from Links with the sibling shared packages available:

```sh
make image-plan
make image
make plan RELEASE_ENV=dev
```

The shared builder snapshots the explicit manifest/source allowlist, resolves
Python and uv through the portfolio image catalog, and builds the
[Containerfile](../ops/containers/Containerfile). `tools/image.py` has been
removed. The runtime contains installed packages and required assets, uses UID
10001, and starts Uvicorn directly. Shared builds default to native Podman;
CI selects Docker through `PLAZIA_CONTAINER_BUILDER`. `CONTAINER` selects
the image smoke, disposable acceptance and standalone Flyway engine.
Compose owns the API readiness healthcheck, so native image formats preserve
the same probe on both engines without a builder-specific format flag.

Release environments are retained names. Exact `production` uses production
policy; `dev`, `staging` and other names all use the preview policy. Native
development is a separate path: use the base Compose topology plus
`compose.dev.yaml` and the generated configuration/secret projections for
loopback port 8000. Shared releases use `compose.release.yaml`, publish no host
port, and attach to admitted PostgreSQL, shared-services and ingress networks.
Only the API joins ingress; schema jobs use only PostgreSQL.

Production routing is `https://links.liberalia.net`. Preview routing is
`https://links-<environment>.liberalia.net`; it is independent of the application
revision. Shared routing owns DNS/tunnel/TLS convergence. The public route
covers public short links, dashboard, callback and API paths through the same
origin. API and worker receive that origin explicitly; the API audience is
`<origin>/api/v1`. Register the dedicated Links browser client's
`<origin>/auth/callback` redirect and API resource with the selected Identity
environment before activation. The client may share the Plazia business;
organization remains the pool authorization boundary.

The provider declaration projects owner/API/worker DSNs and Flyway credentials.
The migration order is prepare → literal Flyway migrate → finish → API/worker.
Redis remains a required external secret binding for API sessions, replay and
rate limits. This pass adds no Redis provider: the inspected current root
capability catalog has none. Identity/OpenFGA installation outputs and SMTP
bindings must come from their owners. Releases require explicit
PLZK_WORKER_SMTP_HOST and PLZK_WORKER_SMTP_FROM; username, port and TLS mode
use the worker TOML section unless explicitly supplied as worker-only
environment overrides. Remote Compose mounts the packaged SQL artifact
at ./flyway, while native development uses the source project.
Worker secrets never enter the API, and
owner/Flyway credentials never enter either runtime.

Shared release activation remains disabled. After Identity deployment succeeds,
complete Links' stateful worker qualification/fencing and admit its workload
into the root production suite. Production operations enter from the Plazia
root aggregate; a leaf `make plan RELEASE_ENV=production` is intentionally
rejected by shared tooling. The API remains suitable for stateless
container replicas or serverless execution with external PostgreSQL/Redis;
the durable email worker still runs separately. No deployment, DNS/tunnel
change, stateful rollout or restore qualification was performed here.

Run the persistent worker separately: uv run python -m worker.run. Serverless API invocations do not drain email jobs. Worker settings use PLZK_WORKER_ selectors and the [worker] TOML section. SMTP security is starttls (default), tls or plain for isolated local capture only; plain SMTP is rejected in production. Timeout 10 seconds, worker idle interval 5 seconds, retry limit 5, exponential delays 30/60/120/240 seconds and cap 3600 seconds. Pending messages survive restart; SMTP acceptance immediately before a crash can duplicate delivery.

Delivery incident diagnosis starts with the worker role: count unsent jobs, attempts>=5 and next_attempt_at, without selecting email addresses. Repair SMTP/configuration first. Manual dead-letter replay changes delivery state and must be a targeted operator action. Retention purges delivered/dead subscribers after 30 days and old unactivated subscriptions after 365 days, cascading their jobs. Link deletion cancels waiting work.

Schema rollback is a restore of the prior database snapshot and matching application revision; never run Flyway clean or redeploy the old ORM runtime against this schema. No live restore, deployment, Identity account, or production inbox gate was exercised by local acceptance.

## CI source contract
The API owns forwarded rate-limit identity. Configure app.trusted_proxy_ips (or PLZK_TRUSTED_PROXY_IPS as a JSON array) with exact immediate proxy addresses, and require that proxy to overwrite X-Forwarded-For or append its observed client as the rightmost address. Unlisted peers cannot select a forwarded identity; duplicate/malformed headers fall back to the direct peer. Keep ASGI proxy-header rewriting disabled so the application can verify the actual peer; the container entrypoint does this explicitly. Without a trusted identity, clients behind an ingress share the peer bucket. An edge that owns per-client admission may disable the application limiter explicitly. Native development has no ingress service; release routing uses the declared shared ingress resource.

For simultaneous local Podman work, pin a session with the native CONTAINER_CONNECTION selector when running image/acceptance lanes. Changing the global connection during a run can split its owned resources across stores. The harness touches only its unique labelled resources.

CI checks out Links and salyvinagre/plazia as siblings and runs the same Make lanes as local development. For private shared sources, configure PLZK_SHARED_SOURCE_TOKEN with read access. The shared checkout must publish the Python 3.14 package manifests consumed by this lockfile; local shared-source changes are not proof of that publication. The disposable acceptance lane uses Docker, a local OAuth issuer and SMTP capture. Workflow execution on GitHub remains unverified here.

## Telemetry
PLZK_TELEMETRY_EXPORT_DRIVER=noop is the API default; the worker uses PLZK_WORKER_TELEMETRY_EXPORT_DRIVER. Set it to otel and configure PLZK_TELEMETRY_OTLP_ENDPOINT for shared OTLP HTTP export. All signals use stable service.name=plazia-links, service.namespace=plazia, version 0.2.0 and the deployment environment; api/worker use distinct instrumentation scopes. Configure the collector and dashboards through the platform owner. Export and queue-sampling failures remain passive. Provider shutdown flushes on normal API/worker exit.

HTTP duration/failure uses shared protocol instrumentation. Links owns activation enqueue/process/provider duration and sent/retry/dead settlement outcomes; worker samples pending/dead jobs, oldest eligible age and leases without recipient or tenant labels. Enqueue latency describes preparation inside the command transaction, while settlement outcomes are emitted after commit. Dead counts cover enabled, activated links; disabled or deleted work is not eligible. The saved local span/metric tests do not establish collector ingestion or production alerting.
