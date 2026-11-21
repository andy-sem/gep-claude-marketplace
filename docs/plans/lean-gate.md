# Lean Gate: simplify `destructive-guard` to "Jev decides, otherwise Claude Code decides"

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> One commit per work package (L0–L5). Every package leaves `uv run pytest`, `uv run ruff check .` and `claude plugin validate .` green. **Status: proposal. Nothing past L0 starts until the decisions in [Decisions](#decisions-to-confirm-before-l1) are confirmed.**

**Goal:** the gate's behaviour is exactly the Lean model in `plugins/destructive-guard/formal/SimpleGate.lean`:

1. call → Jev → risky (`risk > escalate`): `ask`. Not risky: no decision, and Claude Code's own permissions apply.
2. Jev off, misconfigured or down, a call that mentions `.env`, or unreadable hook input: no decision plus a warning (`systemMessage`). Claude Code's own permissions apply.

The plugin never allows and never denies (S1), so it can only add prompts (S5). Everything that exists only to support rules or fail-closed asks is deleted: rule packs, the shell parser, the script scanner, strict mode, Jev's "lift" path and the done-file protocol.

**Spec:** the theses S1–S8 in the module doc of `SimpleGate.lean`. Where this plan and the model disagree, fix the model first (L0), then the code.

**What stays:** `hooks/env-guard.sh` (Read/Edit/Write of `.env*` files is blocked; it is not part of the Jev model and no simpler replacement exists), the Jev client (`jev/client.py`, `request.py`, `prompt.py`, `redactor.py`, `jev/*.json`), `GATE_INFRA_PYTHON` lookup, the `check` skill (reduced), `GATE_LOG`/`GATE_JEV_LOG` (merged).

## Current → target

| Area | Today | Lean gate |
| --- | --- | --- |
| Decision source | rule packs + script scan, Jev on top (escalate / lift / keep) | Jev only |
| Jev safe answer | lifts a rule ask (`allowThreshold`, `canLift`) | no decision (no rules to lift) |
| Jev uncertain band | rule result stands | no decision |
| Jev down / timeout / HTTP / malformed | rule result stands (silent) | no decision + warning |
| Jev misconfigured | `ask gate-config:` | no decision + warning |
| Python missing / too old | `ask unparsable: python unavailable` | no decision + warning |
| Engine exception | `ask gate-config: internal error` | no decision + warning |
| Bad hook stdin | `ask unparsable:` | no decision + warning (`badInput`) |
| `.env` in the call | not sent to Jev, rule result stands | not sent, no decision + warning (`envReference`) |
| Scripts a command runs | collected via the shell parser and sent to Jev | not collected; Jev sees the command only |
| `gate.sh` | done-file protocol, asks on any failure | prints the engine's stdout or a warning JSON; never asks on its own |

### Code to delete (≈ 2 400 of 3 860 lines)

- `lib/destructive_guard/rules/`, `engine/`, `shell/`, `scripts/`, `gate/`, `verdict.py`, `packs/`
- From `config.py`: everything except `GATE_ENABLED`, `GATE_ENV_GUARD`, `GATE_LOG` (and `ProjectDir` path resolution)
- From `jev/config.py`: `allowThreshold`, `canLift`, `scope`. From `jev/decider.py`: the `pass` branch and `rule_result` plumbing (it becomes the `judge` function of the model)
- From `jev/request.py`: `scripts_payload` and the `scripts`/`problems` fields
- Tests: `test_corpus`, `test_packs`, `test_rule_kinds`, `test_rules_loading`, `test_tokenizer`, `test_gate_engine`, `test_gate_scripts`, `test_gate_fn`, `tests/cases/`, `tests/fixtures/`. Rewrite: `test_gate_hook`, `test_gate_hook_jev`, `test_config`, `test_check`, `test_readme`, `test_gate_sh_lookup`, `test_jev_units`, `test_jev_request_py`
- `testkit/`: `bench_gate.py`, `porting.py`, `impl.py`, `stubs.py`, if nothing else uses them after L2. Check with `grep`.

### Environment variables after the change

| Kept | Removed |
| --- | --- |
| `GATE_ENABLED`, `GATE_ENV_GUARD`, `GATE_INFRA_PYTHON`, `GATE_LOG` (now also the Jev audit), `TYPESAFE_API_KEY`, `GATE_JEV_URL`, `GATE_JEV_MODEL`, `GATE_JEV_TIMEOUT_MS`, `GATE_JEV_ESCALATE_THRESHOLD`, `GATE_JEV_PROMPT`, `GATE_JEV_INSTRUCTIONS`, `GATE_JEV_CONTEXT`, `GATE_JEV_POLICY` | `GATE_CHECKS`, `GATE_RULES_FILE`, `GATE_RULES`, `GATE_DISABLE_RULES`, `GATE_STRICT`, `GATE_JEV_ALLOW_THRESHOLD`, `GATE_JEV_CAN_LIFT`, `GATE_JEV_SCOPE`, `GATE_JEV_LOG` (merged into `GATE_LOG`), `GATE_JEV` (see D2) |

A removed variable that is still set triggers a one-time SessionStart warning (see D3), so users upgrading from 0.8 learn their config is ignored.

## Decisions to confirm before L1

| # | Question | Recommendation | Effect on the Lean model |
| --- | --- | --- | --- |
| D1 | Adopt the design? It drops the fail-closed guarantee that the README and `CLAUDE.md` promise, and with zero config the plugin only guards `.env` files. | Yes, if Jev is the product. State it plainly in the README: "without a Jev key this plugin only blocks `.env` files". | none |
| D2 | Is "Jev off" its own state? | No. Remove `GATE_JEV`: Jev is on whenever the gate is enabled; no `TYPESAFE_API_KEY` means misconfigured. `GATE_ENABLED=0` is the only off switch, and it is silent because the hook doesn't run. | `Setting.off` is removed; `Setting` = `misconfigured \| on` |
| D3 | Warn on every call when misconfigured? | **Confirmed 2026-11-21.** No, it would flood every Bash call. Add a `SessionStart` hook that checks the config once (Python found, key present, URL valid, prompt loadable, removed vars set) and prints one warning. At `PreToolUse`, misconfigured gives no decision and no warning. Runtime failures (timeout, HTTP, malformed answer), `.env` skips and bad input still warn per call. | `hook … .misconfigured` returns `⟨none, none⟩`; new `sessionStart` function + thesis S9 "misconfigured ⇒ session warning". S3 and S4 change to "warning or misconfigured ⇒ no decision". |
| D4 | Keep sending scripts to Jev? | No. It needs the shell parser, which is the largest part to delete. Note it in the README as a known blind spot (`bash cleanup.sh` is judged by its name only). | none (scripts were never in the model) |
| D5 | What does `/destructive-guard:check` do with no rules? | **Confirmed 2026-11-21.** Keep it. `--config` prints the effective Jev config with the key redacted. A call check always contacts Jev (drop `--jev`) and prints `ask`/`none` with risk, or the warning. | none |
| D6 | `gated-dev-simple-workflow` planner (`## Gated operations`, `Rule ID` from `check`) | The planner judges calls itself. Rename the column to `Gate` and fill it from `check` only when the user opts in (`dryRunGate: true` in `.claude/gated-dev.json`), because every check now costs a Jev request. Otherwise write `unknown`. | none |
| D7 | Accept the Claude Code assumptions (a hook `ask` overrides a settings allow but not a settings deny; with no hook decision, normal permissions apply; under `bypassPermissions` Jev is the only protection) | Verify each one against the current Claude Code hooks docs in L0 and cite the doc in the model. | Assumptions section gets a source link and the checked CC version |
| D8 | The Lean project now ships to every user who installs the plugin (`plugins/destructive-guard/formal/`) | **Moved 2026-11-21 at the user's request.** Lean is a developer-only tool: users never build the model, and the plugin runs without it. Only the source ships (≈ 10 KB); `.lake/` is gitignored, so build output is never published. | none |

## Work packages

### L0: Lean model builds and matches the decisions

- [x] Lean installed for development with `elan` (official installer, `~/.elan`, no PATH change; Homebrew's `elan-init` builds from source on Intel Macs and is too slow). Not needed by end users.
- [x] `cd plugins/destructive-guard/formal && lake build`: builds with no errors, no warnings and no `sorry` (fixed `asks_iff`, dropped the deprecated `if_false` simp args).
- [x] `lean-toolchain` pinned to `leanprover/lean4:v4.36.0`; `lake-manifest.json` added.
- [ ] Apply D2, D3 and D7 to `SimpleGate.lean`: remove `Setting.off`; misconfigured gives `⟨none, none⟩` at the tool hook; add `sessionStart : Setting → Option Down` and S9; update S3/S4; add `Down.pythonMissing` and `Down.internalError` (used by `gate.sh` and the hook's exception path).
- [ ] Rebuild; the examples at the bottom become the conformance table for L1 (see below).
- [x] Delete `docs/plans/lean-gate-model.md` (it modelled the old rule gate; deleted with the other finished plans, summaries now in the plugin READMEs).
- [x] Add a "Formal model" line to the README Development section and to `CLAUDE.md`: dev-only, needs `elan` (`PATH="$HOME/.elan/bin:$PATH" lake build` in `plugins/destructive-guard/formal`), not needed to use the plugin.
- [ ] Commit: `Lean gate: formal model in destructive-guard/formal`.

### L1: New hook path (old code still present, unused by the hook)

- [ ] `jev/decider.py` → `judge(cfg, result) -> HookOut` exactly as the model: `down(why)` → `none` + warning; `answer(risk)` → `ask` if `risk > escalate`, else `none`. Remove `allowThreshold`, `canLift`, `pass`.
- [ ] `hook.py`: read config → if misconfigured emit nothing; read stdin (fail → `badInput` warning); for `Bash` / `mcp__*` build the payload; `.env` mention → `envReference` warning; else redact, `JevClient.ask_jev`, `judge`. Any exception → `internalError` warning. Output: `permissionDecision: "ask"` + reason, or `{"systemMessage": "destructive-guard: …"}`, or nothing.
- [ ] `gate.sh`: drop the done-file. Python missing/too old → print the `pythonMissing` warning JSON and exit 0. Non-zero rc → `internalError` warning. Never `ask`.
- [ ] New `hooks/session-start.sh` + `lib/destructive_guard/session_check.py` (D3); register a `SessionStart` entry in `hooks/hooks.json`.
- [ ] One `GATE_LOG` record per call: tool, redacted command/input (`null` on `.env`), probabilities or the `Down` reason, decision, latency.
- [ ] `tests/test_lean_conformance.py`: drive the real hook through `testkit` `JevMock` over every combination of {misconfigured, on} × {bad input, `.env` call, clean call} × {timeout, HTTP 500, malformed, risk 0, risk = escalate, risk > escalate} and assert S1–S4, S8 and S9 on the output. Mirror each Lean `example` as a named case.
- [ ] Commit: `Lean gate L1: Jev-only hook`.

### L2: Delete the rule gate

- [ ] Delete the modules, packs and tests listed under [Code to delete](#code-to-delete--2-400-of-3-860-lines); reduce `config.py` and `jev/config.py`; remove `scripts_payload`.
- [ ] Remove now-unused `testkit` helpers; fix `pyproject.toml` `pythonpath`/per-file ignores if a path disappears.
- [ ] `grep -rn "GATE_CHECKS\|GATE_STRICT\|GATE_RULES\|GATE_DISABLE_RULES\|CAN_LIFT\|ALLOW_THRESHOLD\|JEV_SCOPE\|gate-config:\|unparsable:"` over the repo returns only the removed-variable warning list and the changelog.
- [ ] Commit: `Lean gate L2: remove rules, parser and script scan`.

### L3: `check` skill

- [ ] `check/dry_run.py` + `report.py`: `--config` shows the Jev config (key redacted) and the session-start warnings; a call check runs the hook's code path against Jev and prints decision, risk, top choice or the warning. Remove `--jev`, `source`, `rule`.
- [ ] Update `skills/check/SKILL.md` (it costs a Jev request; never pass secrets in the checked call).
- [ ] Commit: `Lean gate L3: check skill on Jev`.

### L4: `gated-dev-simple-workflow` follow-up (D6)

- [ ] `agents/ticket-planner.md`: `## Gated operations` columns `Command`, `Gate`, `Reason`; `Gate` = `ask (jev risk=…)` from `GATE_CHECK`, or `unknown`.
- [ ] `skills/ticket/SKILL.md` step 3: set `GATE_CHECK` only when `dryRunGate` is true; drop "Never pass `--jev`". Document `dryRunGate` in `references/config.md`.
- [ ] `tests/test_watch_pr.py::test_watcher_command_passes_the_gate`: assert no `ask` with Jev mocked safe.
- [ ] Bump the workflow plugin version (plugin.json + catalog).
- [ ] Commit: `gated-dev: gated operations without rule ids`.

### L5: Docs and release

- [ ] README rewrite: what it does (Jev asks on risky calls, `.env` block), what it no longer does (no rules, no fail-closed), the warnings and what each means, env table, the D7 assumptions with the doc link, a migration section from 0.8 (removed variables).
- [ ] `CLAUDE.md`: the `destructive-guard` section (no rules/parser/packs, fail-open with a warning, the formal model location).
- [ ] `test_readme.py` matches the new README.
- [ ] Version `0.8.1` → `1.0.0` (breaking: config removed, fail-closed dropped) in `plugin.json` and the catalog with a new description; bump `metadata.version`.
- [x] `docs/plans/class-refactor/` deleted (summary in the plugin READMEs).
- [ ] `claude plugin validate .`, `jq . .claude-plugin/marketplace.json`, `uv run pytest`, `uv run ruff check .`.
- [ ] Commit: `destructive-guard 1.0.0: lean gate`.

## Review focus

- **S5 is the safety claim**: the plugin never makes a call more permissive than Claude Code alone. Any code path that prints `allow`, `deny` or `"continue": false` breaks it; the conformance test must fail on such output.
- **Redaction before sending (S7)**: the `.env` check runs on the raw payload before redaction, and nothing unredacted reaches `JevClient`.
- **Latency**: Jev is now on every Bash/MCP call. Keep the timeout default (1500 ms) and measure the hook's cold start without Jev (misconfigured path) to make sure it stays well under 100 ms.
- **Warning noise**: a Jev outage gives one warning per call. Check this is acceptable in a real session before L5; if not, rate-limit it to once per minute via a state file in `$TMPDIR` and record the change in the model (warnings become optional, decisions unchanged).
