# Configuration and deployment
All application variables use PLZL_. .env.example is the selector reference. BaseSettings uses the shared RuntimeSettingsSources: explicit constructor input, guarded NAME/NAME_FILE secret selectors, non-secret environment fields, PLZL_CONFIG_FILE TOML, dotenv and mounted secret directories. Secrets are forbidden in TOML. A selector and its _FILE form cannot both be set. Secret files must meet the shared owner-only or immutable container-secret permission contract.

Non-secret TOML uses [app] and [identity] sections. PLZL_CONFIG_FILE selects the file. Runtime selectors include PostgreSQL API/worker DSNs, Redis DSN, SMTP password and the confidential Identity client secret. The API receives only its database role; the worker receives only its worker DSN and SMTP configuration. The worker needs the public origin, but no OAuth client credentials.

PostgreSQL must be version 18 with separate schema owner, links_app and links_worker login roles. Runtime roles must not be superuser or BYPASSRLS and must not inherit owner privileges or the other runtime role. Create roles and database with the provider's provisioning process before migration. The API cannot provision organization bindings or read subscription PII. Identity/OpenFGA membership is managed by Identity, independently of the local activation binding.

## Fresh schema
Set PLZL_DATABASE_URL to the owner DSN for this command only. Set FLYWAY_URL to the JDBC URL, FLYWAY_USER and FLYWAY_PASSWORD through the operator's secret environment. The pinned Flyway container receives only those values, and a read-only SQL project mount.

```sh
make migrate
make schema-check
uv run python -m app.cli bind-organization org_0199a112345670008000000000000001 --name "Example organization"
```

make migrate runs read-only admission, literal Flyway migrate (with validation on migrate), Flyway validate, then read-only catalog verification. Startup compares the packaged migration checksum, security-function bodies/search paths/definer flags, tenant policy expressions, object owners and sensitive runtime grants. Manual security drift is rejected; startup never repairs it. The checksum follows the [Flyway source algorithm](https://github.com/flyway/flyway/blob/flyway-13.4.0/flyway-core/src/main/java/org/flywaydb/core/internal/resolver/ChecksumCalculator.java). Flyway baseline/clean are disabled. Startup never migrates or accepts an unversioned legacy database. There is no customer-data conversion path. Do not change applied migrations; add a new version for later changes.

Only an owner credential can bind/disable organizations. Supply the configured issuer and owner DSN to the operator command; never run the API with that credential. disable-organization revokes existing management sessions on their next request without affecting public destinations.

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

Run from Links with the sibling shared packages available. The image tool materializes a temporary allowlist containing runtime sources and shared package manifests/source trees, excluding repositories, local environments and credentials:
```sh
make image
```
The Dockerfile installs locked non-editable packages, copies the runtime venv and packaged assets, and runs as uid 10001. Compose consumes external providers and separate mounted credential files. Copy infrastructure/.env.example, resolve providers/secrets, and review docker compose config before starting. The included Compose is deployment configuration; this task's evidence is isolated local acceptance, not a production rollout.

Run the persistent worker separately: uv run python -m worker.run. Serverless API invocations do not drain email jobs. SMTP security is starttls (default), tls or plain for isolated local capture only; plain SMTP is rejected in production. Timeout 10 seconds, worker idle interval 5 seconds, retry limit 5, exponential delays 30/60/120/240 seconds and cap 3600 seconds. Pending messages survive restart; SMTP acceptance immediately before a crash can duplicate delivery.

Delivery incident diagnosis starts with the worker role: count unsent jobs, attempts>=5 and next_attempt_at, without selecting email addresses. Repair SMTP/configuration first. Manual dead-letter replay changes delivery state and must be a targeted operator action. Retention purges delivered/dead subscribers after 30 days and old unactivated subscriptions after 365 days, cascading their jobs. Link deletion cancels waiting work.

Schema rollback is a restore of the prior database snapshot and matching application revision; never run Flyway clean or redeploy the old ORM runtime against this schema. No live restore, deployment, Identity account, or production inbox gate was exercised by local acceptance.

## CI source contract
The API owns forwarded rate-limit identity. Configure app.trusted_proxy_ips (or PLZL_TRUSTED_PROXY_IPS as a JSON array) with exact immediate proxy addresses, and require that proxy to overwrite X-Forwarded-For or append its observed client as the rightmost address. Unlisted peers cannot select a forwarded identity; duplicate/malformed headers fall back to the direct peer. Keep ASGI proxy-header rewriting disabled so the application can verify the actual peer; the container entrypoint does this explicitly. Without a trusted identity, clients behind an ingress share the peer bucket. An edge that owns per-client admission may disable the application limiter explicitly. The supplied Compose has no ingress service; its separate Caddyfile is an optional topology requiring this configuration.

For simultaneous local Podman work, pin a session with the native CONTAINER_CONNECTION selector when running image/acceptance lanes. Changing the global connection during a run can split its owned resources across stores. The harness touches only its unique labelled resources.

CI checks out Links and salyvinagre/plazia as siblings and runs the same Make lanes as local development. For private shared sources, configure PLZL_SHARED_SOURCE_TOKEN with read access. The shared checkout must publish the Python 3.14 package manifests consumed by this lockfile; local shared-source changes are not proof of that publication. The disposable acceptance lane uses Docker, a local OAuth issuer and SMTP capture. Workflow execution on GitHub remains unverified here.

## Telemetry
PLZL_TELEMETRY_EXPORT_DRIVER=noop is the local default. Set it to otel and configure PLZL_TELEMETRY_OTLP_ENDPOINT for shared OTLP HTTP export. All signals use stable service.name=plazia-links, service.namespace=plazia, version 0.2.0 and the deployment environment; api/worker use distinct instrumentation scopes. Configure the collector and dashboards through the platform owner. Export and queue-sampling failures remain passive. Provider shutdown flushes on normal API/worker exit.

HTTP duration/failure uses shared protocol instrumentation. Links owns activation enqueue/process/provider duration and sent/retry/dead settlement outcomes; worker samples pending/dead jobs, oldest eligible age and leases without recipient or tenant labels. Enqueue latency describes preparation inside the command transaction, while settlement outcomes are emitted after commit. Dead counts cover enabled, activated links; disabled or deleted work is not eligible. The saved local span/metric tests do not establish collector ingestion or production alerting.
