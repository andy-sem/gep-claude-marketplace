# destructive-guard

Work in progress. See `docs/plans/gated-dev-simple-workflow.md` at the
repository root for the plan and work packages.

## Install

```text
/plugin install destructive-guard --marketplace gep/gep-claude-marketplace
```

## Current state (0.1.0, WP-G1)

The approval-gate engine is ported unchanged in behaviour from its source
project. What it does today:

- **Bash and every MCP tool** go through `hooks/gate.sh` →
  `lib/gate-engine.mjs`. The gate only ever answers `ask` or nothing (normal
  permissions); it never auto-allows. Any engine or config error → `ask`
  with a `gate-config:` reason. Missing `node` → `ask`.
- **Rules** come from the packs in `packs/` (`base`, `postgres`,
  `terraform`), or from one file named by `GATE_RULES`.
  The `destructive` default pack and env-based pack selection
  (`GATE_CHECKS`, ...) arrive in WP-G2/WP-G3.
- **Read/Edit/Write of `.env*` files** are blocked (except `.env.example`).
- **Jev classifier**: off unless `GATE_JEV=1` (needs `TYPESAFE_API_KEY`).
  Its prompt asks whether a call changes cloud services, remote
  infrastructure or databases (provider-neutral).

Requires Node.js on PATH. `jq` is optional.

## Development

```bash
node --test 'plugins/destructive-guard/test/*.test.mjs'
```
