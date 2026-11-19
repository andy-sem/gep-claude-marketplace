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
| Driver | `scripts/ticket-flow/{cli,launch,pick,sync,flow-state}.mjs` | workflow (launcher part, WP-W7); Jira picker dropped | Orca/iTerm, Jira picker |

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
| `GATE_STRICT` | `0` | `1` asks on commands the parser cannot resolve (`$EDITOR f`, `eval "$X"`, `curl … \| bash`); `0` gives them no opinion while still checking the readable parts. |
| `GATE_JEV` | `0` | `1` enables the Jev layer. |
| `TYPESAFE_API_KEY` | — | Required when `GATE_JEV=1`. |
| `GATE_JEV_URL` / `_MODEL` / `_TIMEOUT_MS` | as today | Endpoint, model, timeout (https enforced). |
| `GATE_JEV_ALLOW_THRESHOLD` / `_ESCALATE_THRESHOLD` | `0.95` / `0.5` | As today. |
| `GATE_JEV_PROMPT` | `destructive` | Built-in prompt name (`destructive`, `cloud-change`) or a path to a JSON with `question`, `instructions`, `context`, `criteria`, `ask`, `safe`. **Done.** |
| `GATE_JEV_INSTRUCTIONS` / `_CONTEXT` / `_POLICY` | unset | Replace the question text, `context.project`, `context.policy` of the selected prompt. **Done.** |
| `GATE_JEV_SCOPE` | `bash,mcp` | Which calls are sent to Jev. **Done.** |
| `GATE_JEV_CAN_LIFT` | `1` | Jev may lift a rule `ask` when it is confident the call is safe (today's behaviour). `0` = Jev can only add asks. Jev never emits `allow`. **Done.** |
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
    references/{pipeline-spec,config}.md
  hooks/hooks.json + notify.sh       # notification only (optional, WP-W4)
  scripts/watch-pr.mjs               # only if WP-W5 is accepted
```

Generalisation (unchanged from the first draft, minus everything gate-related):

1. **File-based, no tracker.** The ticket is a Markdown file,
   `<ticketsDir>/<KEY>/ticket.md` (written by the developer, or by the skill
   from a pasted description); the key is free-form (`PROJ-1` or a slug).
   The spec agent reads only that file. No Jira/GitHub-issue integration.
2. **Per-project config** `.claude/gated-dev.json` (all optional):
   `keyPattern`, `ticketsDir`, `setupCommand`,
   `formatCommand`, `riskPaths`, `baseBranchStrategy`, `escalationExtra`,
   `models`.
3. **Gate coupling = contract, not code.** Agents keep the "a gate prompt or
   denial is a checkpoint → `NEEDS_DECISION`" rule. The planner's
   `## Gated operations` table is filled by asking the gate plugin's `check`
   skill when it is installed; otherwise the planner lists commands it
   *expects* to need approval with `Rule ID: unknown`. No path into the other
   plugin is hard-coded.
4. **Keep Orca and iTerm2 support** (user, 2026-11-19): the skill detects
   the host, creates worktrees with `orca worktree create` in Orca and
   `git worktree add` elsewhere, and adopts a linked worktree it was opened
   in. A file-based launcher that opens one session per ticket in Orca or
   iTerm2 tabs is WP-W7 (the source's Jira picker is dropped). Agents
   namespaced as `gated-dev-simple-workflow:ticket-*`.

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
| WP-W2 | **Orchestrator skill**: config file, `ticket.md` intake (file or pasted text), distilled `pipeline-spec.md`, Orca/iTerm2/plain host handling; keeps H1–H7, `NEEDS_DECISION`, `state.json`, scope check, review loop, PR | W1 | Dry run in a scratch repo from a `ticket.md` reaches an opened PR; `--status`/`--resume` work |
| WP-W3 | **Gate integration**: planner uses `destructive-guard:check` when present, `unknown` otherwise | W2, G5 | Plan lists rule ids with the gate installed, `unknown` without |
| WP-W4 | **Notifications** (optional): cross-platform `notify.sh` | W2 | Fires on macOS; silent elsewhere |
| WP-W5 | **PR follow-up** (v0.2, deferred): `watch-pr.mjs`, `--address-review`, merge cleanup | W2 | Feedback round end-to-end on a test PR |
| WP-W6 | **Docs & release** | W1–W3 | README covers config + ticket files |
| WP-W7 | **Launcher**: port `launch.mjs` (host detection, `sessionName`, iTerm2 AppleScript tab, `orca terminal create`, Orca worktree per ticket) as a file-based CLI: open a `/ticket <KEY>` session per given key or per `ticket.md` without a run; sets `TICKET_FLOW_KEY`; tests ported | W2 | Dry-run output correct for Orca and iTerm2; a real tab opens in each |

Order: G0 → G1 → G2 → G3 → G4 → G5 → G6, and in parallel W1 → W2 → W3 → W6 (W7 after W2).
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
| Ticket source for the workflow | Files only (`ticket.md` per ticket); no Jira or other tracker (user, 2026-11-19) |
| PR watcher / `--address-review` / merge cleanup | Deferred to v0.2 (WP-W5) |
| Orca / iTerm2 | Kept: host handling in the skill (W2), launcher (W7) (user, 2026-11-19) |
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

Start a session with: *"Read `docs/plans/gated-dev-simple-workflow.md` §7 and
start the next open work package."*

Last updated 2026-11-19 (night). Branch `feature/gated-dev-simple-workflow`,
earlier work merged into `main` (PRs #2, #3); dry-run/W6 in PR #4.
destructive-guard **0.6.1**, gated-dev-simple-workflow **0.5.0**, catalog
`metadata.version` **0.13.0**. Tests: 730 (guard) + 37 (launcher) green;
`claude plugin validate .` passes.

### Status

| Package | State | Commit |
| --- | --- | --- |
| WP-G0, WP-W0 | Done: both plugins scaffolded and in the catalog | `480382f` |
| WP-G1 | Done: engine ported, packs, `.env` guard, 523 tests | `256a169` |
| WP-G2 | Done: general destructive gate is the default (no config needed) | `ec6a090` |
| WP-G4 (prompt part) | Done ahead of G3: Jev prompt is data, destructive by default, env-configurable | `5384607` |
| WP-G3 | Done: `lib/config.mjs`, pack selection, opt-outs, `GATE_ENABLED`, `GATE_ENV_GUARD`, `GATE_LOG`, `GATE_STRICT` (default 0), 713 tests | `c6a5eb5` |
| WP-G4 (rest) | Done: `GATE_JEV_SCOPE`, `GATE_JEV_CAN_LIFT`, 718 tests | `7d5f6f0` |
| WP-G5 | Done: `check` skill + `lib/check.mjs` (dry-run, `--json`, `--config`), 728 tests | `885c418` |
| WP-W1 | Done: four agents ported, file-based (`ticket.md`), generic escalation + `PROJECT_RULES:`, `FORMAT_CMD=`, optional `GATE_CHECK=` | `3119c41` |
| WP-W2 | Done: `/ticket` skill + `references/{pipeline-spec,config}.md`; end-to-end runs to a PR in the demo repo (see "Dry run results"); Orca/adoption fixes from the run in `b056f39` | `92efa87`, `b056f39` |
| WP-W3 | Done: skill passes `GATE_CHECK=node '<installPath>/lib/check.mjs' --json --cwd '<wt>'` when the `destructive-guard:check` skill is available (path from `~/.claude/plugins/installed_plugins.json`); planner checks every changing call, lists `ask` ones with `source` as rule ID | `506d0f7` |
| W2/W3 dry run | Done: DEMO-1/2/3 ran to `done` (PRs #1–#3); `--status`, interrupt + `--resume`, a gated row with real rule IDs and the `unknown` path all checked (see "Dry run results") | this commit |
| WP-G6 | Done: README rewritten (install, every env variable with defaults, what Jev sends, writing rules incl. all rule kinds and top-level keys, troubleshooting); `test/readme.test.mjs` fails when an env variable, pack or prompt is undocumented; CI `.github/workflows/test.yml` (jq manifest check + `node --test`, Node 22); root README lists the plugins; 730 tests | `1d3db86` |
| WP-W7 | Done: `scripts/launch.mjs` (file-based CLI: keys or `--all`, `--dry-run`, `--remote-control`; new ticket → Orca worktree via `orca worktree create --repo path:<root>` when the repo is registered in Orca, else main checkout; existing run → `--resume` in its worktree; `done` skipped), `skills/launch/SKILL.md`, 37 tests in `test/launch.test.mjs` (CI runs them). Real tabs verified 2026-11-19 against the demo repo: Orca (repo registered → new Orca worktree under Orca's workspace dir, ticket + local settings copied, session adopted it with the plugin loaded) and iTerm2 (main checkout, titled tab). Version 0.4.0 | `fa7c24a` |
| WP-W4 | Open, optional: notifications | |
| WP-W5 | Deferred to v0.2: PR watch, `--address-review`, merge cleanup | |
| WP-W6 | Done: README without the WIP line, ticket files + `state.json` stages, config example (JSON backslash note); version 0.5.0 | this commit |

Suggested order from here: push and open the PR (ask the user first), demo cleanup (ask). W4 optional; W5 is v0.2. Every other package is complete.

### Progress in the session of 2026-11-19 (W1–W3)

- User decisions this session (binding, also in §5): the workflow is
  **file-based, no Jira**; **keep Orca and iTerm2 support**.
- W1: agents ported and generalised (no tracker tools; read-only stages only
  disallow `Edit, NotebookEdit`).
- W2: `/ticket` skill written from the source skill (sections kept and dropped
  listed below); kickoff git commands smoke-tested in a scratch repo.
- W3: gate integration; `GATE_CHECK` form tested against the local
  `check.mjs` (`rm -rf` → `rm-recursive-force`, `DROP TABLE` via MCP →
  `mcp-destructive-sql`, `npm test` → none; the planner's own check call is
  not gated).
- Not yet exercised: the skill as a whole (no `/ticket` run so far).

### Progress in the session of 2026-11-19, evening (G6, dry run, W7)

- **G6** (`1d3db86`): destructive-guard README is the full user reference;
  `test/readme.test.mjs` fails when an env variable, pack or Jev prompt is
  undocumented; CI `.github/workflows/test.yml` (jq manifest check, both
  plugins' `node --test`, Node 22); root README lists both plugins.
- **W7** (`fa7c24a`): `scripts/launch.mjs`, `skills/launch/SKILL.md`,
  `test/launch.test.mjs` (37), README section. Real tabs opened in Orca and
  iTerm2.
- A parallel session committed `822c2f0` (CLAUDE.md rewrite) and `b056f39`
  (Orca: `--repo path:<root>`, plain git worktrees when the repo is not
  registered in Orca; kickoff adopts an existing `<KEY>/*` worktree without
  state; Reuse adopts the worktree that already has the branch).

### Dry run results (demo repo)

Setup: private repo `gep/gated-dev-demo`, clone `~/work/gep/gated-dev-demo`
(Node project, `npm test`). Both plugins are installed there from this
checkout with **local scope** (`.claude/settings.local.json`, local directory
marketplace). The plugin cache is a copy: after changing a plugin, run
`claude plugin update <plugin>@gep-claude-marketplace` there (from the demo
dir) before the next run. The demo repo is registered in Orca
(`orca repo add`).

| Run | How | Result |
| --- | --- | --- |
| DEMO-1 | `/ticket` by hand | `done`, PR #1 **merged**. Planner used `GATE_CHECK`; it chose `git rm -r legacy`, so the `## Gated operations` table was `None` (every call `decision: none`) |
| DEMO-2 | launcher, Orca | Orca worktree `~/orca/workspaces/gated-dev-demo/demo-2-add-truncate-helper` created and adopted, plugin loaded. **Stopped at config validation**: the demo's `main` has an invalid `.claude/gated-dev.json` (the `keyPattern` was written with a single backslash, `-\d+`, which is not valid JSON; a setup bug, not the plugin's). The skill reported it correctly. The fix is uncommitted in the demo main checkout |
| DEMO-3 | launcher, iTerm2 | `done`, PR #2 **open** (session started in the main checkout, created `.claude/worktrees/demo-3-add-reverse-helper`) |

Later runs (2026-11-19 night, headless `claude -p` in the demo dir, Orca host):

| Run | Check | Result |
| --- | --- | --- |
| DEMO-2 | resumed in its Orca worktree after the config fix | `done`, PR #3 merged |
| DEMO-2 | `--status` | Correct report; `decisions.md` was missing from the file list (fixed in SKILL.md §2) |
| DEMO-4 | gated row (`rm -rf`, `git push origin --delete`) | H1 first: spec found the branch absent on `origin` and asked (good). After the answer the plan's table had `git-push-force` and `rm-recursive-force` from `GATE_CHECK`. The planner also listed `rm -rf coverage` that only an npm script runs; planner prompt now lists only calls a step runs. Left at `awaiting_plan_approval` |
| DEMO-5 | `unknown` path (guard disabled with `--settings` enabledPlugins false) | No `GATE_CHECK`; table row `rm -rf …` with `Rule ID: unknown` |
| DEMO-5 | approve, kill at stage `dev`, `--resume` | Re-entered dev, review PASS, stopped at `complete` when `gh` was denied (treated as a checkpoint). Branch pushed (a `Bash(git push:*)` deny does not match `git -C <wt> push`); no PR |

Note: `git-push-force` also covers `--delete`/`--prune`/`--mirror` (documented); the id was kept so `GATE_DISABLE_RULES` values stay valid. With `GATE_ENABLED=0` the dry run returns `none` for everything, so `unknown` appears only when the guard plugin is absent or disabled.

Finding worth keeping: the launcher reads `.claude/gated-dev.json` from the
main checkout, the session in an Orca worktree reads the base branch's copy.
They can differ (as with DEMO-2). Acceptable; the session reports it.

### Next

1. Merge PR #4 (dry-run checks, W6) when the user approves.
2. Demo cleanup done 2026-11-19: PR #2 closed, all ticket branches (local and
   remote) and worktrees removed, demo `main` up to date. Kept: the repo, its
   `orca repo` entry and the local-scope plugin install (for further runs).
3. Optional: WP-W4 (notifications). v0.2: WP-W5.

Update the Status table at the end of every work package.

### Decisions made with the user (binding)

- **Public repo hygiene.** This repo is public. Never write the source
  project's app name, ticket keys, cloud/database project ids or branch names
  here. Supabase and gcloud/GCP are *irrelevant*: no packs, rules, prompt text
  or test names for them (tests use fictional tools: `cloudctl`, `blobctl`,
  `dwh`, `dbhost`, `acmecloud`). The source branch is kept only in local
  Claude memory (`gated-dev-source-refs`); ask the user if it is missing.
  History was rewritten once to remove such strings; do not reintroduce them.
- **MCP stays generic.** No named MCP servers (Jira/Atlassian, Chrome, …) in
  prompts, packs or tests; describe calls as "an MCP tool call that …" and use
  made-up tool names (`mcp__tracker__editIssue`, `mcp__db__execute_sql`).
  A test enforces this for `jev/*.json`.
- **General gate first, then fine-tuning and configuration.** The default
  must be useful with zero config; G3+ only add selection/opt-outs on top.
- **`GATE_STRICT` defaults to 0** (low noise for a global gate): parser
  uncertainty gives no opinion; `GATE_STRICT=1` restores asking.
- **Jev decides, rules are the fallback.** With Jev on, Jev's confident answer
  wins (adds an ask, or lifts a rule ask); rules decide in the uncertain band,
  on errors/timeouts and when Jev is off. Fail-closed cases (config errors,
  unparsable hook input) always ask and are never sent to Jev.
- **The Jev question is a default that env vars can change** (done):
  `GATE_JEV_PROMPT`, `GATE_JEV_INSTRUCTIONS`, `GATE_JEV_CONTEXT`,
  `GATE_JEV_POLICY`. The default covers local *and* remote destructive calls.
- CLI rules for `gh`, `aws`, `az`, `wrangler` stay in the destructive pack
  (command coverage, not MCP).
- **The workflow is file-based; no Jira support.** The ticket is
  `TICKET_DIR/ticket.md`; agents have no tracker tools or tracker wording.
- Commit per work package; push only when the user asks.

### Where things are (`plugins/destructive-guard/`)

| Path | What |
| --- | --- |
| `hooks/hooks.json` | PreToolUse: `Bash\|mcp__.*` → `gate.sh`; `Read\|Edit\|Write` → `env-guard.sh` |
| `hooks/gate.sh` | Fail-closed wrapper: runs the engine with `GATE_RUN=1` + done-file; no done-file / no node → ask. Honours `GATE_INFRA_NODE` (tests) |
| `hooks/gate.sh` / `env-guard.sh` | Both exit early on `GATE_ENABLED=0`; env guard also on `GATE_ENV_GUARD=0` |
| `hooks/env-guard.sh` | Blocks file names `.env`, `.env.*`, `*.env` except `.env.example` (exit 2); jq optional |
| `lib/check.mjs` | Dry-run CLI for the `check` skill: `checkCall()`, `effectiveConfig()`, `run(argv)`; Jev only with `--jev`; `source` = reason prefix (rule id or gate tag) |
| `skills/check/SKILL.md` | `/destructive-guard:check`: command as **one single-quoted argument** (unquoted words would be parsed by the gate as part of the skill's own call) |
| `lib/config.mjs` | `readConfig(env)` (all non-Jev env parsing, throws `ConfigError`), `buildRules(config)` (packs + files − disabled ids), `availablePacks()` |
| `lib/gate-engine.mjs` | Parser, rules, `classify(input, rules, {strict})`, `gate(input, rules, {strict, trace})`, `main()` (config → rules → gate → `GATE_LOG`); `DEFAULT_PACKS = ["base","destructive"]`; `composeRules/loadPacks/parseRules/packPath` |
| `lib/gate-scripts.mjs` | Collects scripts a Bash command runs; `scanScripts()` (program names of rules with `scriptScan !== false`, then `scriptPatterns`) |
| `lib/gate-jev.mjs` | Jev config (`readJevConfig`), prompts (`promptFromEnv`, `builtinPrompt`, `validatePrompt`), redaction, request, `jevDecision`, audit log |
| `packs/base.json` | wrappers, runners, inert programs (always loaded) |
| `packs/destructive.json` | Default rules (34): filesystem, git, gh, infra, aws/az/wrangler, SQL, MCP |
| `packs/postgres.json`, `packs/terraform.json` | Optional, ported; selected with `GATE_CHECKS` |
| `jev/destructive.json` | Default Jev prompt: choices `read_only`, `reversible_change` (safe), `destructive` (ask) |
| `jev/cloud-change.json` | Preset: the source's question (cloud/infra/db changes) |
| `test/fixtures/rules.json` | Ported ruleset with fictional tool names; used by the ported tests |
| `test/destructive.test.mjs` | One case per destructive rule + near misses + new rule-field unit tests |
| `test/config.test.mjs` | Config matrix, `buildRules`, strict/loose classify, hook-level config, `GATE_LOG`, env guard |
| `test/jev-prompt.test.mjs` | Default prompt, env overrides, validation, "no specific names" check |
| `README.md` | User docs: what it asks on, Jev section, rule-field reference |

### Behaviour today

- **Env vars that work now:** everything in §2's table. `GATE_RULES` is kept as a
  deprecated alias for `GATE_CHECKS=none GATE_RULES_FILE=…` (tests use it).
- **Strict vs loose:** `classify()` defaults to `strict: true` (tests and
  library callers keep the old behaviour); `main()` passes `config.strict`
  (default false). Loose mode parses nested shell strings containing `$`,
  skips unreadable segments and checks the rest.
- **Decision flow** `gate()`: `classify()` (rules) → for Bash with no rule hit
  (or Jev on) collect scripts and `scanScripts()` → `applyJev()` when
  `GATE_JEV=1`. Jev: risk = sum of prompt `ask` choices > escalate threshold →
  ask; sum of `safe` choices ≥ allow threshold → no opinion (lifts rule asks);
  otherwise the rule result. Commands mentioning `.env` are never sent.
  `applyJev()` skips calls outside `cfg.scope` (no request); `runJev()`
  ignores a `pass` when `cfg.canLift === false`.
- **Rule kinds:** `cli-allowlist`, `cli-gated`, `mcp-allowlist`, `mcp-as-cli`,
  and new `mcp-pattern` (`tool` regex, `toolWords` from the name after the
  last `__` split on `_`/`-`/camelCase, `inputPattern` over all input
  strings; all given conditions must hold).
- **New `cli-gated` fields (G2):** `whenFlags` (AND of OR-groups),
  `shortBundles` (one-letter flags inside `-rf`; also for `unlessFlags`),
  `whenArgs` (regex on any arg; `ignoreCase`; `matchStdin` adds heredocs),
  `dynamicArgs` (`ask` default / `ignore`), `scriptScan` (`false` keeps the
  program out of the scanner). Destructive rules use `dynamicArgs: "ignore"`
  and `scriptScan: false`.
- The scanner returns early when no program names and no `scriptPatterns`
  are loaded (so with the default packs, outside-project scripts don't ask).

### Agent prompt contract (WP-W1, `plugins/gated-dev-simple-workflow/agents/`)

All four: `WORKTREE=`, `KEY=`, `TICKET_DIR=` (default
`<WORKTREE>/docs/tickets/<KEY>`), `BASE_BRANCH=`, `DECISIONS:` (YAML),
optional `PROJECT_RULES:` (from config `escalationExtra`). Final line is
`RESULT: OK <file>` or a `NEEDS_DECISION` block (`stage:` spec/plan/dev/review).

- `ticket-spec`: reads `TICKET_DIR/ticket.md` only (the skill must write it
  before stage 1); writes `spec.md`.
- `ticket-planner`: optional `GATE_CHECK=<command>` (W3: the skill passes a
  `destructive-guard` check `--json` command when that plugin is installed);
  without it, `Rule ID` is `unknown`. Optional `FEEDBACK:`. Writes `plan.md`.
- `ticket-dev`: `MODE=implement|fix-review|fix-pr`, `REVIEW_ROUND=`,
  `FEEDBACK=<file>` (fix-pr, used by v0.2/W5), optional `FORMAT_CMD=`
  (config `formatCommand`). Commits with `Plan-Step:`/`Review-Fix:`/`PR-Fix:`
  trailers; writes `dev-report.md`.
- `ticket-reviewer`: optional `REVIEW_SINCE=`; writes `review.md` ending in
  `VERDICT: PASS|CHANGES_REQUIRED`.
- Read-only stages have `disallowedTools: Edit, NotebookEdit`; the skill
  checks `git diff --name-only` after them (only `TICKET_DIR` may change).

### The `/ticket` skill (WP-W2, `skills/ticket/`)

- Sections: 0 config + host, 1 arguments, 2 status, 3 kickoff, 4 prompt/parse/
  scope check, 5 spec, 6 plan + H2, 7 dev + H6, 8 review loop + H5, 9 resume,
  9a complete (verify, push, PR), 10 abort. Source sections 9b–9d
  (`--address-review`, PR watch, merge cleanup) and all tracker comments are
  left out (W5 / dropped).
- Intake: `<session-root>/<ticketsDir>/<KEY>/ticket.md`, or pasted text the
  skill writes there; copied into the worktree; committed at H2 with spec/plan.
  Front matter `base:` overrides the base branch.
- Base: front matter → config `baseBranch` → `origin/HEAD` → `main`.
- `state.json` and `/.claude/worktrees/` are ignored via `.git/info/exclude`.
- Config `.claude/gated-dev.json`: `ticketsDir`, `keyPattern`, `baseBranch`,
  `setupCommand`, `formatCommand`, `riskPaths`, `escalationExtra`, `models`
  (unknown key → stop).
- Host `orca` / `iterm` / `plain` (same test as the source's `detectHost`);
  `TICKET_FLOW_KEY` set means a launched session (no `/rename` hint).

### Then: WP-W7 (launcher)

- Source: `scripts/ticket-flow/launch.mjs` (+ `launch.test.mjs`); fetch it
  again into the new session's scratchpad (see "Getting the source"); keep `detectHost`, `sessionName`/`shortSummary`,
  `buildShellCommand` (`TICKET_FLOW_KEY`, `claude --name`, optional
  `--remote-control`), `buildAppleScript`, `buildOrcaArgs`,
  `createOrcaWorktree`, `launchTab`. Key validation from config `keyPattern`;
  summary from the `ticket.md` title; base from §3 step 2 rules. Drop
  `pick.mjs`, `resolveBase` parent lookup and `PIPELINE_FILES` (the skill
  comes from the plugin now).

### Known gaps / later

- Not caught statically: destructive commands inside scripts (`bash x.sh`
  running `rm -rf`), `psql -f file.sql`, SQL piped into a client. Jev covers
  these when enabled.
- Old commit `1a9ae6b` may still be fetchable on GitHub by SHA until GC;
  GitHub support can purge it if needed.

### Getting the source (only needed for WP-W4 and WP-W5 now)

SSH clone of `git@github.com:omicron-labs/flashcards.git` hung. Fetch single
files with `gh` (authenticated) into the session scratchpad, never this repo:

```bash
REF="$SOURCE_REF"   # not recorded here (public repo); local memory or ask the user
gh api "repos/omicron-labs/flashcards/contents/<path>?ref=$REF" \
  -H 'Accept: application/vnd.github.raw' > <dest>
gh api "repos/omicron-labs/flashcards/git/trees/$REF?recursive=1" --jq '.tree[].path'
```

Remaining workflow sources (W7's launcher is done):
`.claude/hooks/notify-ticket-flow.sh` (W4),
`scripts/ticket-flow/watch-pr.mjs` and sections 9b–9d of
`.claude/skills/ticket/SKILL.md` (W5, v0.2). Scrub all
source-project names (see decisions above) while porting.

### Working rules for every package

1. Keep existing tests green, then change behaviour; add tests per change.
2. Run `node --test 'plugins/destructive-guard/test/*.test.mjs'` (Node 25
   rejects a bare directory argument) and `claude plugin validate .` before
   committing.
3. Bump the plugin `version` in `plugin.json` **and** its catalog entry, and
   `metadata.version` when the catalog changes (see `CLAUDE.md`).
4. One commit per work package on `feature/gated-dev-simple-workflow`; push
   only when the user asks.
