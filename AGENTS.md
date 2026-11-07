# Agent instructions

## Start

- Read [README.md](README.md) for product, contract and validation guidance.
- Locate shared principles with `uv run plazia-tools principles path`; read the core and relevant topics.

## Ownership

- Preserve verified organization ownership, OpenFGA authority, local bindings and idempotent mutation contracts.
- Treat `/openapi.json` as the generated wire contract; retain existing public identifiers unless an explicit migration changes them.
- Use the README's Jinja/HTMX/daisyUI asset workflow for this product; do not treat shared Svelte guidance as an implicit frontend migration.
- Keep provider credentials and ignored runtime state private; use Linear for work state.

## Validation

- Use Make and the declared `.plazia/quality.yaml` lanes; rebuild assets with `make frontend` when their sources change.
- Distinguish isolated acceptance fixtures from live Identity, inbox delivery and production deployment.
