# Plan: `destructive-guard` + `gated-dev-simple-workflow` plugins

Port the `/ticket` pipeline (skill, four stage agents) and the approval gate
(deterministic rules engine + optional Jev classifier) from
`omicron-labs/flashcards` (source branch: `$SOURCE_REF`, see handoff) into
this marketplace as **two independent plugins**:

| Plugin | Purpose | Ships |
| --- | --- | --- |
| `destructive-guard` | Deterministic PreToolUse approval gate, optional Jev layer. Installed once, globally; configured only through env variables. Default: ask before destructive commands. | hooks, gate engine, rule packs, a `check` skill |
| `gated-dev-simple-workflow` | Ticket → spec → plan → dev → review → PR pipeline. Knows nothing about gate internals; works with or without the gate plugin. | skill `ticket`, four agents |

Principle: **workflow and gates are separate.** The gate protects every
session (human or agent); the workflow only *expects* that gated calls may
prompt and treats them as checkpoints.

Branch: `feature/gated-dev-simple-workflow`. Work is tracked in this file, not
in Jira.

## 1. What exists in the source

| Piece | Source path | Goes to | Project coupling |
| --- | --- | --- | --- |
| Gate engine | `.claude/hooks/gate-infra.mjs`, `gate-infra.sh` | gate | None: tool-agnostic, reads a rules JSON, fails closed |
| Script scanner | `.claude/hooks/gate-scripts.mjs` | gate | Low |
| Jev layer | `.claude/hooks/gate-jev.mjs` | gate | Logic generic; `CONTEXT`/`CRITERIA` prompt named the source project's cloud and database projects (now generic) |
| Rules | `.claude/hooks/gate-rules.json` | gate (as packs) | Cloud-provider rules dropped; Postgres / Terraform kept as optional packs |
| `.env` guard | inline in `.claude/settings.json` | gate | None |
| Gate tests | `.claude/hooks/*.test.mjs` (~3.2k lines) | gate | Paths assume `.claude/hooks/` |
| Orchestrator skill | `.claude/skills/ticket/SKILL.md` | workflow | High: Jira, `pnpm`, Orca, `scripts/ticket-flow/*`, the pipeline design spec in `docs/tickets/` |
| Stage agents | `.claude/agents/ticket-*.md` | workflow | Medium: source-ticket docs, shared database rules, `pnpm format:files` |
| Notify hook | `.claude/hooks/notify-ticket-flow.sh` | workflow | macOS-only |
| PR watcher | `scripts/ticket-flow/watch-pr.mjs` | workflow (optional) | Low |
| Driver | `scripts/ticket-flow/{cli,launch,pick,sync,flow-state}.mjs` | dropped | Orca/iTerm, Jira picker |

Engine gap found: rule kinds are `cli-allowlist`, `cli-gated` (program +
positional subcommand prefixes), `mcp-allowlist`, `mcp-as-cli`. They cannot
express **flag-based** danger (`git push --force`, `rm -rf`, `git clean -fdx`)
or **content-based** danger (`DROP TABLE` in `psql -c` or an MCP
`execute_sql`). The destructive default needs both (gate WP-G2).

## 2. Plugin A: `destructive-guard`

### Layout

```text
plugins/destructive-guard/
  .claude-plugin/plugin.json
  README.md
  hooks/
    hooks.json            # PreToolUse: Bash|mcp__.* → gate; Edit|Write|Read → .env guard
    gate.sh               # fail-closed wrapper (was gate-infra.sh)
  lib/
    gate-engine.mjs       # was gate-infra.mjs
    gate-scripts.mjs
    gate-jev.mjs
    config.mjs            # env → effective config (single place)
  packs/                  # built-in rule packs, selected by GATE_CHECKS
    base.json             # wrappers, runners, inert programs (always loaded)
    destructive.json      # DEFAULT
    postgres.json  terraform.json   # optional, ported from the source
    kubernetes.json  aws.json       # optional, new, later
  jev/
    destructive.json      # default Jev prompt (context + criteria)
    cloud-change.json     # optional: the source prompt, provider-neutral
  skills/check/SKILL.md   # "/destructive-guard:check <cmd>": dry-run + show config
  test/*.test.mjs
```

### Configuration (env only)

Set in `~/.claude/settings.json` `env` for global defaults, or in a project's
`.claude/settings.json` `env` to override per project. No config files are
required; files are only referenced *by* env variables.

| Variable | Default | Meaning |
| --- | --- | --- |
| `GATE_ENABLED` | `1` | `0` turns the whole gate off (hooks become no-ops). |
| `GATE_CHECKS` | `destructive` | Comma list of built-in packs (`destructive,postgres,terraform,...`), or `none`. |
| `GATE_RULES_FILE` | unset | Extra rules file(s), `:`-separated; appended after the packs. With `GATE_CHECKS=none` this is a full replacement. |
| `GATE_DISABLE_RULES` | unset | Comma list of rule ids to drop from the loaded packs (fine-grained opt-out). |
| `GATE_ENV_GUARD` | `1` | Block Read/Edit/Write of `.env*` (except `.env.example`). |
| `GATE_LOG` | unset | Append one JSON line per decision (audit/debug). |
| `GATE_JEV` | `0` | `1` enables the Jev layer. |
| `TYPESAFE_API_KEY` | — | Required when `GATE_JEV=1`. |
| `GATE_JEV_URL` / `_MODEL` / `_TIMEOUT_MS` | as today | Endpoint, model, timeout (https enforced). |
| `GATE_JEV_ALLOW_THRESHOLD` / `_ESCALATE_THRESHOLD` | `0.95` / `0.5` | As today. |
| `GATE_JEV_PROMPT` | `destructive` | Built-in prompt name (`destructive`, `cloud-change`) or a path to a JSON with `question`, `instructions`, `context`, `criteria`, `ask`, `safe`. **Done.** |
| `GATE_JEV_INSTRUCTIONS` / `_CONTEXT` / `_POLICY` | unset | Replace the question text, `context.project`, `context.policy` of the selected prompt. **Done.** |
| `GATE_JEV_SCOPE` | `bash,mcp` | Which calls are sent to Jev. |
| `GATE_JEV_CAN_LIFT` | `1` | Jev may lift a rule `ask` when it is confident the call is safe (today's behaviour). `0` = Jev can only add asks. Jev never emits `allow`. |
| `GATE_JEV_LOG` | unset | As today. |

Invariants kept from the source: fail closed (any config/engine error →
`ask` with a `gate-config:` reason), never emit `allow`, invalid config is
reported, not guessed.

### `destructive` pack (default) — initial content

Definition: a call is destructive when it deletes, overwrites or irreversibly
changes data or resources, **on the local machine or in any cloud/remote
service**. Creating or deploying is not destructive by itself (that is what
the optional packs and the `cloud-change` Jev prompt are for).

- **Filesystem**: `rm` with `-r`/`-R`/`--recursive` *and* `-f` (any spelling,
  combined or split), `find … -delete`, `shred`, `dd of=`, `mkfs*`, `truncate`.
- **Git**: `push --force|-f|--force-with-lease|--mirror|--delete`, `push … :ref`,
  `reset --hard`, `clean -f…`, `branch -D`, `checkout -- .`/`restore .` on the
  worktree, `stash drop|clear`, `filter-branch`, `update-ref -d`, `tag -d` + push.
- **GitHub CLI**: `gh repo delete`, `gh release delete`, `gh pr close --delete-branch`.
- **Infra**: `terraform|tofu destroy`, `apply -destroy`, `state rm`;
  `kubectl delete`, `helm uninstall`; `docker system prune`, `volume rm`.
- **Cloud CLIs** (delete/destroy verbs only, reads and creates pass):
  `aws … delete-*|terminate-*|rm|rb`, `az … delete`, `wrangler … delete`.
- **MCP tools**: any `mcp__*` tool whose name contains `delete|drop|destroy|remove|reset|truncate`,
  plus SQL-content matching for MCP SQL tools (below).
- **SQL content** (in `psql -c`, `-f` files via the script scanner, MCP SQL
  tools): `DROP`, `TRUNCATE`, `DELETE` without `WHERE`, `ALTER … DROP`.

Exact list is decided in WP-G2 with tests per entry.

## 3. Plugin B: `gated-dev-simple-workflow`

```text
plugins/gated-dev-simple-workflow/
  .claude-plugin/plugin.json
  README.md
  agents/ticket-{spec,planner,dev,reviewer}.md
  skills/ticket/
    SKILL.md
    references/{pipeline-spec,ticket-sources,config}.md
  hooks/hooks.json + notify.sh       # notification only (optional, WP-W4)
  scripts/watch-pr.mjs               # only if WP-W5 is accepted
```

Generalisation (unchanged from the first draft, minus everything gate-related):

1. **Ticket source pluggable**: `jira` (Atlassian MCP, **default**, today's
   behaviour), `github` (via `gh`), `none` (pasted description, free slug key).
2. **Per-project config** `.claude/gated-dev.json` (all optional):
   `ticketSource`, `keyPattern`, `ticketsDir`, `setupCommand`,
   `formatCommand`, `riskPaths`, `baseBranchStrategy`, `escalationExtra`,
   `models`.
3. **Gate coupling = contract, not code.** Agents keep the "a gate prompt or
   denial is a checkpoint → `NEEDS_DECISION`" rule. The planner's
   `## Gated operations` table is filled by asking the gate plugin's `check`
   skill when it is installed; otherwise the planner lists commands it
   *expects* to need approval with `Rule ID: unknown`. No path into the other
   plugin is hard-coded.
4. Drop Orca/driver; plain `git worktree`. Agents namespaced as
   `gated-dev-simple-workflow:ticket-*`.

## 4. Work packages

### Guard plugin (`destructive-guard`)

| # | Package | Depends on | Done when |
| --- | --- | --- | --- |
| WP-G0 | Scaffold plugin + catalog entry | — | `claude plugin validate .` passes |
| WP-G1 | **Port engine as-is**: engine, script scanner, wrapper, tests; `hooks.json` with `${CLAUDE_PLUGIN_ROOT}`; loads one rules file (the flashcards ruleset split into packs) | G0 | Ported tests green unchanged in behaviour |
| WP-G2 | **New rule capabilities + destructive pack**: flag matching (`whenFlags`, short-flag bundles like `-rf`), argument regex, `mcp-pattern` kind for SQL/content in MCP inputs, SQL detection in `psql -c`; write `destructive.json` with one test per entry | G1 | Destructive matrix test green; `ls`, `git status`, `git push` pass; `git push -f` asks |
| WP-G3 | **Env configuration**: `config.mjs`, pack composition (`GATE_CHECKS`, `GATE_RULES_FILE`, `GATE_DISABLE_RULES`), `GATE_ENABLED`, `GATE_ENV_GUARD`, `GATE_LOG`; bad values → fail-closed ask | G1 | Config matrix tests green |
| WP-G4 | **Jev generalisation** (prompt part done early): prompt from `GATE_JEV_PROMPT` (built-in `destructive` default, `cloud-change` preset, or file); `GATE_JEV_SCOPE`, `GATE_JEV_CAN_LIFT`; no source-project names in code | G3 | Jev tests green against local mock server |
| WP-G5 | **`check` skill**: dry-run a command/MCP call through the effective config and print decision + rule id; print effective config (redacting the API key) | G3 | Skill answers for sample commands |
| WP-G6 | **Docs & release**: README (install, env reference, writing rules, what Jev sends), version bumps, optional CI running `node --test` | G2–G5 | README covers every variable |

### Workflow plugin (`gated-dev-simple-workflow`)

| # | Package | Depends on | Done when |
| --- | --- | --- | --- |
| WP-W0 | Scaffold (**done**; description to be updated: no hooks/gate) | — | validate passes |
| WP-W1 | **Agents**: port four agents, generic escalation list + `PROJECT_RULES:`, `FORMAT_CMD=`, neutral examples, gate-as-contract wording | W0 | No source-project ticket keys, app names or branch names; agents load |
| WP-W2 | **Orchestrator skill**: config file, ticket-source adapter, distilled `pipeline-spec.md`, no Orca/driver; keeps H1–H7, `NEEDS_DECISION`, `state.json`, scope check, review loop, PR | W1 | Dry run in a scratch repo with `ticketSource: none` reaches an opened PR; `--status`/`--resume` work |
| WP-W3 | **Gate integration**: planner uses `destructive-guard:check` when present, `unknown` otherwise | W2, G5 | Plan lists rule ids with the gate installed, `unknown` without |
| WP-W4 | **Notifications** (optional): cross-platform `notify.sh` | W2 | Fires on macOS; silent elsewhere |
| WP-W5 | **PR follow-up** (v0.2, deferred): `watch-pr.mjs`, `--address-review`, merge cleanup | W2 | Feedback round end-to-end on a test PR |
| WP-W6 | **Docs & release** | W1–W3 | README covers config + ticket sources |

Order: G0 → G1 → G2 → G3 → G4 → G5 → G6, and in parallel W1 → W2 → W3 → W6.
**General gate first, then fine-tuning and configuration:** G2 makes the gate a
working general-purpose destructive gate on its own (default, no config
needed); G3+ add selection, opt-outs and the optional packs on top.
The two tracks only meet at W3.

## 5. Decisions

| Decision | Outcome |
| --- | --- |
| Guard plugin name | `destructive-guard` (env variables keep the `GATE_*` prefix, matching the source and the Jev variables) |
| What `destructive` covers by default | Anything destructive, local machine *or* cloud services (§2). The `destructive` Jev prompt uses the same definition. |
| Jev may lift rule asks by default? | Yes (`GATE_JEV_CAN_LIFT=1`, today's behaviour); `0` to restrict Jev to adding asks |
| Default ticket source for the workflow | `jira`; `github` and `none` as alternatives |
| PR watcher / `--address-review` / merge cleanup | Deferred to v0.2 (WP-W5) |
| `.env` guard lives in the guard plugin | Yes, on by default, `GATE_ENV_GUARD=0` to disable |

## 6. Risks

- **Global hook, every session.** Default pack must be precise (low false
  positives) or users disable it; mitigated by per-entry tests and
  `GATE_DISABLE_RULES`.
- **Env-only config** can't express complex rules inline; that is what
  `GATE_RULES_FILE` is for.
- **Jev sends redacted commands to an external API.** Off by default; README
  states what is sent; https enforced.
- **Node required** for the gate; wrapper asks (never allows) without it.
- **Behaviour drift during the port.** Port tests first (G1), change after.

## 7. Handoff (how to continue in a new session)

Start a session with: *"Read `docs/plans/gated-dev-simple-workflow.md` and
start the next open work package."*

### Status

| Package | State |
| --- | --- |
| WP-G0, WP-W0 | Done: both plugin dirs scaffolded, listed in `marketplace.json` (`metadata.version` 0.2.0), validate passes |
| WP-G1 | Done (destructive-guard 0.1.0, catalog 0.3.0): engine/scanner/Jev in `lib/`, wrapper `hooks/gate.sh`, `hooks/hooks.json`, `.env` guard `hooks/env-guard.sh`; ruleset split into `packs/{base,postgres,terraform}.json` (cloud-provider packs removed); 515 ported tests + 8 new green |
| WP-G2 | Done (destructive-guard 0.2.0, catalog 0.4.0): `packs/destructive.json` (34 rules with base) is the default; new `cli-gated` fields `whenFlags`, `shortBundles`, `whenArgs`, `ignoreCase`, `matchStdin`, `dynamicArgs`, `scriptScan`; new kind `mcp-pattern`; 682 tests green |
| WP-G4 (prompt part) | Done ahead of G3 (destructive-guard 0.3.0, catalog 0.5.0): Jev prompt is data (`jev/destructive.json` default, `jev/cloud-change.json` preset), selected by `GATE_JEV_PROMPT`, overridable by `GATE_JEV_INSTRUCTIONS/_CONTEXT/_POLICY`; `ask`/`safe` choice lists drive `jevDecision`. Prompts name no specific MCP server. Remaining G4: `GATE_JEV_SCOPE`, `GATE_JEV_CAN_LIFT` |
| WP-G3 | **Next**: env configuration and tuning. WP-W1 can run in parallel |

#### WP-G2 notes (read before G3)

- `DEFAULT_PACKS = ["base", "destructive"]`; `postgres`/`terraform` are only
  reachable through `GATE_RULES` until `GATE_CHECKS` exists.
- Destructive rules use `dynamicArgs: "ignore"` (otherwise `rm $F` or
  `git checkout $B` would ask) and `scriptScan: false` (otherwise every script
  mentioning `git`/`rm` would ask). The scanner now returns early when no rule
  program and no `scriptPatterns` are loaded, so scripts outside the project no
  longer ask by default.
- Not covered statically: destructive commands inside scripts (`bash x.sh`
  that runs `rm -rf`), `psql -f file.sql`, SQL piped into a client. Jev covers
  these when enabled. Candidates for G3+.
- Tuning candidates for G3: `unparsable: dynamic command word` (`$EDITOR f`)
  asks today, which is noisy for a global gate (`GATE_STRICT=0`?); the `.env`
  guard's `*.env*` match.

#### WP-G1 notes (read before G2/G3)

- Default without `GATE_RULES` = `DEFAULT_PACKS` in `lib/gate-engine.mjs`
  (`base`, `postgres`, `terraform`). G2 makes `destructive` the default; G3
  adds `GATE_CHECKS`, and `postgres`/`terraform` become opt-in. `GATE_RULES=""` now means "use packs"
  (the source treated it as a path).
- New engine exports: `composeRules(paths)` (merge raw packs: string lists
  deduped, `runners`/`rules` concatenated, `inertUnsafeFlags` merged per
  program, duplicate rule ids rejected), `loadPacks(paths)`, `parseRules(obj)`,
  `packPath(name)`. G3 builds pack selection on these.
- Ported tests run against `test/fixtures/rules.json`: the source ruleset with
  its cloud-provider tools renamed to fictional ones (`cloudctl`, `blobctl`,
  `dwh`, `dbhost`, `acmecloud`) so engine coverage of `cli-allowlist`,
  `mcp-allowlist` and `mcp-as-cli` is kept. `test/packs.test.mjs` checks the
  shipped packs match the fixture's matching parts. Its `scriptScanExempt` paths are source-project specific
  and are **not** shipped in any pack (project exemptions → `GATE_RULES_FILE`).
- Three tests that read source-repo files were rewritten: the hook-registration
  test now checks `hooks/hooks.json`; the two "real provision script" tests use
  a temp-project stand-in.
- `.env` guard keeps the source's `*.env*` match, which also blocks e.g.
  `config.environment.ts`. Tighten in G3 together with `GATE_ENV_GUARD`.
- Wrapper still honours `GATE_INFRA_NODE` (tests use it); rename in G3 if wanted.

Update this table at the end of every work package.

### Getting the source

SSH clone of `git@github.com:omicron-labs/flashcards.git` hung in the first
session. Fetch single files with `gh` instead (it is authenticated):

```bash
REF="$SOURCE_REF"   # not recorded here (public repo); ask the user or check local memory
gh api "repos/omicron-labs/flashcards/contents/<path>?ref=$REF" \
  -H 'Accept: application/vnd.github.raw' > <dest>
# list files:
gh api "repos/omicron-labs/flashcards/git/trees/$REF?recursive=1" --jq '.tree[].path'
```

Download into the session scratchpad, not into this repo. Files needed: the
paths in §1, all under `.claude/` plus `scripts/ticket-flow/watch-pr.mjs`
(v0.2 only) and the pipeline design spec in `docs/tickets/` (design reference for WP-W2).

### Engine facts (so G1–G4 don't need re-discovery)

- `gate-infra.sh` runs `node gate-infra.mjs` with `GATE_RUN=1` and
  `GATE_DONE_FILE`; it emits nothing (= no opinion, normal permissions) **only**
  if the engine wrote the done-file, otherwise it emits an `ask`. Missing
  `node` → `ask`.
- Rules path today: `$GATE_RULES` or `gate-rules.json` next to the engine
  (`main()` in `gate-infra.mjs`). `loadRules()` validates and throws
  `RulesError` → `ask` with `gate-config:` reason.
- Rules file top-level keys: `wrappers`, `runners`, `inertPrograms`,
  `inertUnsafeFlags`, `scriptPatterns`, `scriptScanExempt`, `rules`.
- Rule kinds (`KNOWN_KINDS`): `cli-allowlist` (programs, skipWords,
  readPrefixes, readSequences, readVerbs, writeVerbs, helpFlags, helpWords;
  unknown subcommand asks), `cli-gated` (programs, gatedPrefixes matched as a
  subsequence of positionals, unlessFlags), `mcp-allowlist` (tool regex,
  readTools regexes), `mcp-as-cli` (tool regex, argsField, program).
  No flag-based or content-based matching yet → WP-G2.
- Decision flow `gate()`: `classify()` (rules) → for Bash with no rule match
  (or when Jev is on) `gate-scripts.mjs` collects the scripts/files the command
  runs and `scanScripts()` matches `scriptPatterns` → `applyJev()` (dynamic
  import of `gate-jev.mjs`, only when `GATE_JEV` is set).
- Jev: `readJevConfig(env)` parses all `GATE_JEV_*` vars and throws
  `JevConfigError` on bad values; `CONTEXT` and `CRITERIA` constants hold the
  source-project-specific prompt (move to `jev/*.json` in WP-G4); `jevDecision()`
  applies thresholds; request failures leave the rule result unchanged.
- Tests use `node:test`; `gate-hook.test.mjs` computes `repoRoot` as two levels
  up from the hooks dir and spawns the wrapper. Paths need adjusting for
  `plugins/destructive-guard/{hooks,lib,test}`.
- Hooks in plugins reference files via `${CLAUDE_PLUGIN_ROOT}`; plugin agents
  are namespaced (`gated-dev-simple-workflow:ticket-spec`).

### Working rules for every package

1. Port tests first, keep them green, then change behaviour.
2. Run `node --test 'plugins/destructive-guard/test/*.test.mjs'` (Node 25
   rejects a bare directory argument) and
   `claude plugin validate .` before committing.
3. Bump the plugin `version` in `plugin.json` **and** its catalog entry, and
   `metadata.version` when the catalog changes (see `CLAUDE.md`).
4. One commit (or PR) per work package on `feature/gated-dev-simple-workflow`.
