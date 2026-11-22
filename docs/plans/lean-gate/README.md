# Lean gate: `destructive-guard` 1.0, "Jev decides; if Jev cannot, a person does"

> **Status: detailed plan, decisions answered.** The first version of this plan (2026-11-21, commit
> `78ee774`, deleted in `e64fcdb`, restored here) was a proposal: only L0's Lean
> model was built, L1–L5 never started because the decisions were never answered.
> This version keeps that design and adds the implementation detail. **D1, D2, D4
> and D12 were answered on 2026-11-22, so L1 is no longer blocked by decisions**
> (see [Decisions](#decisions)).
>
> **Changed 2026-11-22 (D1, D2, D4, D12):** D1 and D2 confirmed as proposed. D4:
> scripts a command runs stay sent to Jev, so the shell parser and the script
> scanner stay. D12: bad hook input, no Python and internal errors ask, with the
> error as the reason, instead of giving no decision.
>
> **Changed 2026-11-22 (D11):** when Jev is configured but does not answer
> (timeout, HTTP error, network error, malformed answer), the hook warns **and
> asks**. The first version fell back to Claude Code's own permissions there.

## How to use this plan

One file per work package, one commit per package, in this order. Each file
lists what it depends on and ends with the same "Done when" checks. Read this
README (goal, decisions, risks) before starting any package.

| # | Package | Depends on | Blocked by |
| --- | --- | --- | --- |
| 1 | [L0: Lean model + Claude Code assumptions](L0-lean-model.md) | – | – |
| 2 | [LJ0: tests against the real Jev, CI job](LJ0-live-jev-tests.md) | – (parallel to L0) | – |
| 3 | [L1: Jev-only hook, session warning, conformance + live hook tests](L1-jev-only-hook.md) | L0, LJ0 | – |
| 4 | [L2: delete the rule gate](L2-delete-rule-gate.md) | L1 | – |
| 5 | [L3: model ↔ code traceability](L3-traceability.md) | L0, L1 | – |
| 6 | [L4: `check` skill on Jev](L4-check-skill.md) | L1, L2 | – |
| 7 | [L5: gated-dev follow-up](L5-gated-dev.md) | L4 | D6 (option b assumed) |
| 8 | [L6: docs and 1.0.0 release](L6-release.md) | all | – |

Rules for every package: work on a branch from `main`; keep the public repo
hygiene in `CLAUDE.md` (fictional tool names, no named MCP servers); add tests
with every behaviour change; stop and ask when a finding contradicts the Lean
model or an assumption in L0.

## Goal

The gate behaves exactly like the Lean model in
`plugins/destructive-guard/formal/SimpleGate.lean`:

1. A Bash or MCP call goes to Jev (redacted). Risky (`risk > escalate`): `ask`.
   Otherwise: no decision, and Claude Code's own permissions apply.
2. Jev is configured but unavailable (timeout, HTTP error including 429/529
   past the time budget, network error, malformed answer): a warning
   (`systemMessage`) **and** `ask`, so a person decides the call (D11).
3. Jev misconfigured (no key, bad URL or prompt): no decision, silent per call,
   one warning at session start (D3).
4. A call that mentions `.env`: not sent to Jev, no decision, plus a warning.
   Claude Code's own permissions apply.
5. A plugin fault (unreadable hook input, no suitable Python, an internal
   error): `ask` with the error as the reason, plus a warning, whether or not a
   Jev key is set (D12). `gate.sh` asks by itself when it finds no Python.

The plugin never prints `allow` or `deny` (S1), so it can only add prompts (S5).
Everything that exists only for rules or for fail-closed asks is deleted: rule
packs, the rule engine, strict mode, Jev's "lift" path, the done-file protocol.
The shell parser and the script scanner stay: scripts a command runs are still
sent to Jev (D4).

**Spec:** theses S1–S10 in `SimpleGate.lean`. Where code and model disagree, fix
the model first, then the code.

## Decisions

| # | Question | Status | Answer used by this plan |
| --- | --- | --- | --- |
| D1 | Adopt the design? Drops the fail-closed guarantee; without a Jev key the plugin only blocks `.env` files (plus a one-time session warning). | **confirmed 2026-11-22: yes** | Yes. The README says it plainly. |
| D2 | Is "Jev off" its own state? | **confirmed 2026-11-22: yes, remove** | No. `GATE_JEV` is removed. Jev is on whenever the gate is enabled; no `TYPESAFE_API_KEY` = misconfigured. `GATE_ENABLED=0` is the only off switch. |
| D3 | Warn on every call when misconfigured? | confirmed 2026-11-21 | No. A `SessionStart` hook warns once; at `PreToolUse` misconfigured = no decision, no warning. Runtime failures (timeout, HTTP, malformed), `.env` skips and bad input warn per call. |
| D4 | Stop sending scripts a command runs to Jev? (proposed: yes) | **answered 2026-11-22: no, keep sending scripts** | Keep sending. The shell parser and the script scanner stay, and `redact_script` stays. No blind spot for scripts. |
| D5 | `/destructive-guard:check` without rules | confirmed 2026-11-21 | Kept. `--config` prints the Jev config (key redacted) and the session warnings; a call check always contacts Jev (`--jev` removed) and prints `ask`/`none` with the risk, or the warning. |
| D6 | gated-dev planner `## Gated operations` table | explained 2026-11-21, no answer | Option b: column `Gate`, filled from `check` only when `.claude/gated-dev.json` has `"dryRunGate": true` (each check costs a Jev request and sends the command); otherwise `unknown`. |
| D7 | Claude Code assumptions in the model | explained 2026-11-21, no answer | Verified in L0 against the hooks docs and a throwaway hook; results recorded in the model's assumptions section with links and the Claude Code version. |
| D8 | Lean ships with the plugin | confirmed 2026-11-21 | Source only (~10 KB), dev-only, `.lake/` gitignored. Done. |
| D9 | MCP input that mentions `.env` (new) | proposed | Follow the model: skip the call (no request, `envReference` warning), the same as Bash. Today's code instead drops the `.env` lines from MCP input and sends the rest. |
| D10 | Noise during a Jev outage (new) | proposed | With D11 every gated call prompts while Jev is down; that is intended. The `systemMessage` can be rate-limited to once a minute via a state file in `$TMPDIR` if it is too noisy in the L6 trial (the ask reason still names the cause on every prompt). The way out of a long outage is `GATE_ENABLED=0`, which the warning mentions. |
| D11 | Jev configured but unavailable | **confirmed 2026-11-22** | Warning **and** ask. Reason `jev-unavailable: timeout after 1500 ms` (or `http 503`, `network`, `malformed answer`). Applies to calls that were sent; `.env` calls are never sent, so they are not "unavailable". |
| D12 | Bad hook input, no Python, internal error (new) | **answered 2026-11-22: ask** | Ask, with the error as the reason, always (with or without `TYPESAFE_API_KEY`). Warning plus `ask`, like D11. `gate.sh` asks by itself when no Python is found. `S1` and `S5` still hold. |

## Current → target

| Area | Today (0.8.x) | Lean gate (1.0.0) |
| --- | --- | --- |
| Decision source | rule packs + script scan, Jev optional on top | Jev only |
| Jev safe answer | lifts a rule ask (`allowThreshold`, `canLift`) | no decision |
| Jev uncertain band | rule result stands | no decision |
| Jev down / timeout / HTTP / network / malformed | rule result stands, silent | **ask** + warning (D11) |
| Jev misconfigured (no key, bad URL, bad prompt) | `ask gate-config:` on every call | no decision, silent per call; one warning at session start |
| Python missing / too old | `ask unparsable: python unavailable` | **ask** + warning, reason names the error (D12); `gate.sh` asks by itself |
| Engine exception | `ask gate-config: internal error` | **ask** + warning, reason names the error (D12) |
| Bad hook stdin | `ask unparsable:` | **ask** + warning, reason names the error (D12) |
| `.env` in a Bash call | not sent, rule result stands | not sent, no decision + warning |
| `.env` in an MCP call | `.env` lines dropped, rest sent | not sent, no decision + warning (D9) |
| Scripts a command runs | collected via the shell parser, sent to Jev | same (D4): the parser and the scanner stay |
| `gate.sh` | done-file, asks on any failure | prints the engine's stdout; asks with a warning on a plugin fault (no Python, engine exit ≠ 0); never allows or denies |
| `env-guard.sh` | blocks `.env*` for Read/Edit/Write | unchanged |

## Target layout

```text
plugins/destructive-guard/
  hooks/hooks.json            PreToolUse Bash|mcp__.* → gate.sh; Read|Edit|Write → env-guard.sh;
                              SessionStart → session-start.sh (new)
  hooks/gate.sh               interpreter lookup, run gate_main.py, else ask JSON (plugin fault, D12)
  hooks/session-start.sh      interpreter lookup, run session_main.py, else warning JSON (new)
  hooks/env-guard.sh          unchanged
  lib/gate_main.py            unchanged stub → destructive_guard.hook
  lib/session_main.py         new stub → destructive_guard.session
  lib/check.py                unchanged stub → destructive_guard.check.cli
  lib/destructive_guard/
    config.py                 GateConfig: GATE_ENABLED, GATE_ENV_GUARD, GATE_LOG only
    paths.py                  unchanged
    shell/                    unchanged: the parser stays (D4)
    scripts/                  unchanged: the script scanner stays (D4)
    errors.py                 ConfigError, JevConfigError, UsageError (RulesError goes; UnparsableError stays if the parser raises it)
    outcome.py                new: Down (enum), HookOut (decision + warning) and its JSON rendering
    hook.py                   GateHook: the model's `hook` function
    session.py                new: SessionCheck: the model's `sessionStart` function
    log.py                    new: GateLog, one JSON line per call (replaces both logs)
    jev/config.py             JevConfig: key, URL, model, timeout, escalate, prompt
    jev/judge.py              new (replaces decider.py): the model's `judge` function
    jev/client.py             unchanged
    jev/request.py            scripts and problems kept (D4); MCP .env check
    jev/prompt.py             `safe` becomes optional
    jev/redactor.py           unchanged: redact_script stays (D4)
    check/{cli,dry_run,report}.py   rewritten on the hook path
  jev/*.json                  unchanged
  formal/SimpleGate.lean      updated in L0
  skills/check/SKILL.md       rewritten in L4
```

Deleted: `engine/`, `rules/`, `gate/`, `verdict.py`,
`packs/`, `jev/decider.py`, `tests/cases/`, `tests/fixtures/`,
`tests/PORTING.md`.

Size: today `lib/destructive_guard` is ~4 400 lines. About 1 350 go
(`engine` 663, `rules` 361, `gate` 118, parts of `config.py`, `jev/`, `check/`);
`shell` (433) and `scripts` (818) stay. The new modules add ~400.

## Environment variables after the change

| Kept | Removed (warned about once at session start) |
| --- | --- |
| `GATE_ENABLED`, `GATE_ENV_GUARD`, `GATE_INFRA_PYTHON`, `GATE_LOG`, `TYPESAFE_API_KEY`, `GATE_JEV_URL`, `GATE_JEV_MODEL`, `GATE_JEV_TIMEOUT_MS`, `GATE_JEV_ESCALATE_THRESHOLD`, `GATE_JEV_PROMPT`, `GATE_JEV_INSTRUCTIONS`, `GATE_JEV_CONTEXT`, `GATE_JEV_POLICY` | `GATE_JEV`, `GATE_CHECKS`, `GATE_RULES_FILE`, `GATE_RULES`, `GATE_DISABLE_RULES`, `GATE_STRICT`, `GATE_JEV_ALLOW_THRESHOLD`, `GATE_JEV_CAN_LIFT`, `GATE_JEV_SCOPE`, `GATE_JEV_LOG` |

## Risks and review focus

- **S5 is the safety claim.** Any path that prints `allow`, `deny` or
  `"continue": false` breaks it. `HookOut` cannot represent them; the
  conformance test also scans raw stdout.
- **D7 is unproved by Lean.** If Claude Code lets a settings `allow` beat a hook
  `ask`, Jev cannot gate allow-listed commands; if bypass mode ignores hook
  asks, the plugin does nothing there. L0 must check before L1 starts.
- **Redaction before sending (S7).** The `.env` check runs on the raw payload;
  only `build_state` output reaches `JevClient`.
- **Latency.** Every Bash/MCP call now waits on Jev (default budget 1500 ms).
  Measure p50/p95 in the L6 trial; the timeout stays configurable.
- **Privacy.** Every Bash command and MCP input (redacted) leaves the machine
  once a key is set. The README says so in the first paragraph.
- **Outage = prompts.** While Jev is down, every Bash/MCP call prompts (D11),
  after waiting out the timeout budget. Unattended agents stop at the first
  call; that is the intended trade-off. The warning names `GATE_ENABLED=0` as
  the way out.
- **Broken install = prompts.** Bad hook input, no Python and internal errors
  ask on every Bash/MCP call, with the error as the reason (D12). The way out
  is `GATE_ENABLED=0`, which the warning names.
- **Blind spots.** `.env`-mentioning calls are judged only by Claude Code's own
  permissions. Scripts are covered (D4).
