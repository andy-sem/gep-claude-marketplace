# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **public** Claude Code plugin marketplace (`gep-claude-marketplace`): a catalog (`.claude-plugin/marketplace.json`) plus plugin directories under `plugins/`. Users consume it with:

```text
/plugin marketplace add gep/gep-claude-marketplace
/plugin install <plugin-name>@gep-claude-marketplace
```

## The concept: gates and workflow are separate

The two plugins are independent and installable on their own:

| Plugin | What it is | Ships |
| --- | --- | --- |
| `destructive-guard` | Deterministic `PreToolUse` approval gate. Installed once, globally; protects every session (human or agent). Configured **only through env variables**; useful with zero config. | hooks, gate engine, rule packs, Jev prompts, `check` skill |
| `gated-dev-simple-workflow` | File-based ticket → spec → plan → dev → review → PR pipeline (`/ticket`). Knows nothing about gate internals; works with or without the gate and treats any gate prompt or denial as a checkpoint, never something to work around. | `ticket` skill, four stage agents |

### `destructive-guard` (`plugins/destructive-guard/`)

- `hooks/hooks.json`: `Bash|mcp__.*` → `hooks/gate.sh` (fail-closed wrapper around `lib/gate-engine.mjs`); `Read|Edit|Write` → `hooks/env-guard.sh` (blocks `.env*` files except `.env.example`).
- The gate **asks or has no opinion; it never allows**. It parses shell commands (sees through `sudo`, `xargs`, `bash -c`, `npx`) rather than grepping. Engine or config errors ask with a `gate-config:` reason.
- `lib/config.mjs` is the single place that turns env vars into config. Main vars: `GATE_ENABLED`, `GATE_CHECKS` (packs: `destructive` default, `postgres`, `terraform`; `base` always loaded), `GATE_RULES_FILE`, `GATE_DISABLE_RULES`, `GATE_STRICT` (default `0`), `GATE_LOG`, `GATE_JEV_*`.
- Rule packs live in `packs/*.json`; `lib/gate-scripts.mjs` scans scripts a command runs.
- Optional **Jev** classifier (`lib/gate-jev.mjs`, prompts in `jev/*.json`, off by default). With Jev on, its confident answer wins; rules decide in the uncertain band, on errors and when Jev is off. Fail-closed cases always ask and are never sent to Jev.
- `skills/check` + `lib/check.mjs`: dry-run a command/MCP call through the gate, or print effective config (`/destructive-guard:check`).
- The README is the user-facing reference for rules and configuration; keep it in sync with behaviour.

### `gated-dev-simple-workflow` (`plugins/gated-dev-simple-workflow/`)

- `skills/ticket/SKILL.md` is the orchestrator: it runs in the main session, never writes product code, and drives one subagent per stage in a worktree per ticket (`git worktree`, Orca or iTerm2).
- Agents in `agents/`: `ticket-spec` → `spec.md`, `ticket-planner` → `plan.md`, `ticket-dev` → commits + `dev-report.md`, `ticket-reviewer` → `review.md`. Each ends with `RESULT: OK <file>` or a `NEEDS_DECISION` block.
- File-based: the ticket is `docs/tickets/<KEY>/ticket.md` by default, and stages read/write files next to it. **No issue tracker (no Jira)**: agents have no tracker tools or wording.
- Plan approval is always a stop point; after it the run commits, pushes and opens a PR with `gh`.
- With `destructive-guard` enabled the planner dry-runs its calls through `destructive-guard:check` and lists the ones that will ask in the plan's `## Gated operations` table.
- Per-project settings: `.claude/gated-dev.json` (see `skills/ticket/references/config.md`); pipeline contract in `skills/ticket/references/pipeline-spec.md`.

## Work in progress

The branch `feature/gated-dev-simple-workflow` ports both plugins. Its plan, status, binding decisions and handoff are in `docs/plans/gated-dev-simple-workflow.md` (§7 is the entry point for a new session). Read it before changing either plugin.

## Public repo hygiene (binding)

- Never write the source project's app name, ticket keys, cloud/database project ids or branch names here. Use neutral placeholders (`my-app-dev`, `apps/web`, `PROJ-1`).
- No provider-specific packs, rules, prompt text or tests for Supabase or GCP/gcloud. Tests use fictional tools (`cloudctl`, `blobctl`, `dwh`, `dbhost`, `acmecloud`).
- Keep MCP generic: no named MCP servers in prompts, packs or tests; use made-up tool names (`mcp__tracker__editIssue`, `mcp__db__execute_sql`). A test enforces this for `jev/*.json`.

## Test and validate

There is no build step. Before committing:

```bash
node --test 'plugins/destructive-guard/test/*.test.mjs'   # quote the glob; Node 25 rejects a bare directory
claude plugin validate .                                    # marketplace + plugin manifests
jq . .claude-plugin/marketplace.json
```

`destructive-guard` needs Node.js; there are no npm dependencies. Keep existing tests green and add tests with every behaviour change. `gated-dev-simple-workflow` has no automated tests (Markdown skills and agents).

## Adding or changing a plugin

Every plugin lives in two places that must stay in sync:

1. **Plugin directory** `plugins/<name>/` with `.claude-plugin/plugin.json` (unique `name`, `version`, `description`, `author`, `license` Apache-2.0, `keywords`).
   - Skills: `skills/<skill-name>/SKILL.md` with YAML frontmatter `name` and `description`.
   - Agents in `agents/`, hooks in `hooks/hooks.json` (reference files via `${CLAUDE_PLUGIN_ROOT}`); commands and MCP config are also allowed.
2. **Catalog entry** in `.claude-plugin/marketplace.json` under `plugins`, with `source: "./plugins/<name>"` and the same `version` and `description`.

When a plugin changes, bump its `version` and update its description in **both** `plugin.json` and the catalog entry, and bump `metadata.version` in `marketplace.json`.

## Git

One commit per work package; push only when the user asks.
