# Lean Gate: `destructive-guard` 1.0, "Jev decides, otherwise Claude Code decides"

> Branch `lean-gate-plan` (from `main` at `c6ef18b`, after PR #10). One commit per work package (L0–L6); every package leaves
> `uv run pytest`, `uv run ruff check .`, `claude plugin validate .` and the Lean
> build green. Push only when asked.
>
> **Status: detailed plan.** The first version of this plan (2026-11-21, commit
> `78ee774`, deleted in `e64fcdb`, restored here) was a proposal: only L0's Lean
> model was built, L1–L5 never started because D1, D2 and D4 were never answered.
> This version keeps that design and adds the implementation detail. **L1 does
> not start until D1, D2 and D4 are confirmed** (see [Decisions](#decisions)).

## Goal

The gate behaves exactly like the Lean model in
`plugins/destructive-guard/formal/SimpleGate.lean`:

1. A Bash or MCP call goes to Jev (redacted). Risky (`risk > escalate`): `ask`.
   Otherwise: no decision, and Claude Code's own permissions apply.
2. Jev misconfigured, down, timed out or malformed, a call that mentions `.env`,
   unreadable hook input, no suitable Python, an internal error: no decision
   plus, where useful, a warning (`systemMessage`). Claude Code's own
   permissions apply.

The plugin never prints `allow` or `deny` (S1), so it can only add prompts (S5).
Everything that exists only for rules or for fail-closed asks is deleted: rule
packs, the shell parser, the script scanner, strict mode, Jev's "lift" path,
the done-file protocol.

**Spec:** theses S1–S9 in `SimpleGate.lean`. Where code and model disagree, fix
the model first, then the code.

## Decisions

| # | Question | Status | Answer used by this plan |
| --- | --- | --- | --- |
| D1 | Adopt the design? Drops the fail-closed guarantee; without a Jev key the plugin only blocks `.env` files (plus a one-time session warning). | **open** | Yes. The README says it plainly. |
| D2 | Is "Jev off" its own state? | **open** | No. `GATE_JEV` is removed. Jev is on whenever the gate is enabled; no `TYPESAFE_API_KEY` = misconfigured. `GATE_ENABLED=0` is the only off switch. |
| D3 | Warn on every call when misconfigured? | confirmed 2026-11-21 | No. A `SessionStart` hook warns once; at `PreToolUse` misconfigured = no decision, no warning. Runtime failures (timeout, HTTP, malformed), `.env` skips and bad input warn per call. |
| D4 | Keep sending scripts a command runs to Jev? | **open** | No. Needs the shell parser. Documented blind spot: `bash cleanup.sh` is judged by its text only. |
| D5 | `/destructive-guard:check` without rules | confirmed 2026-11-21 | Kept. `--config` prints the Jev config (key redacted) and the session warnings; a call check always contacts Jev (`--jev` removed) and prints `ask`/`none` with the risk, or the warning. |
| D6 | gated-dev planner `## Gated operations` table | explained 2026-11-21, no answer | Option b: column `Gate`, filled from `check` only when `.claude/gated-dev.json` has `"dryRunGate": true` (each check costs a Jev request and sends the command); otherwise `unknown`. |
| D7 | Claude Code assumptions in the model | explained 2026-11-21, no answer | Verified in L0 against the hooks docs and a throwaway hook; results recorded in the model's assumptions section with links and the Claude Code version. |
| D8 | Lean ships with the plugin | confirmed 2026-11-21 | Source only (~10 KB), dev-only, `.lake/` gitignored. Done. |
| D9 | MCP input that mentions `.env` (new) | proposed | Follow the model: skip the call (no request, `envReference` warning), the same as Bash. Today's code instead drops the `.env` lines from MCP input and sends the rest. |
| D10 | Warning noise during a Jev outage (new) | proposed | One warning per call at first; if that is too noisy in the L5 trial, rate-limit to once a minute via a state file in `$TMPDIR` (warnings become optional in the model; decisions unchanged). |

## Current → target

| Area | Today (0.8.x) | Lean gate (1.0.0) |
| --- | --- | --- |
| Decision source | rule packs + script scan, Jev optional on top | Jev only |
| Jev safe answer | lifts a rule ask (`allowThreshold`, `canLift`) | no decision |
| Jev uncertain band | rule result stands | no decision |
| Jev down / timeout / HTTP / malformed | rule result stands, silent | no decision + warning |
| Jev misconfigured (no key, bad URL, bad prompt) | `ask gate-config:` on every call | no decision, silent per call; one warning at session start |
| Python missing / too old | `ask unparsable: python unavailable` | no decision + warning |
| Engine exception | `ask gate-config: internal error` | no decision + warning |
| Bad hook stdin | `ask unparsable:` | no decision + warning |
| `.env` in a Bash call | not sent, rule result stands | not sent, no decision + warning |
| `.env` in an MCP call | `.env` lines dropped, rest sent | not sent, no decision + warning (D9) |
| Scripts a command runs | collected via the shell parser, sent to Jev | not collected (D4) |
| `gate.sh` | done-file, asks on any failure | prints the engine's stdout or a warning; never asks itself |
| `env-guard.sh` | blocks `.env*` for Read/Edit/Write | unchanged |

## Target layout

```text
plugins/destructive-guard/
  hooks/hooks.json            PreToolUse Bash|mcp__.* → gate.sh; Read|Edit|Write → env-guard.sh;
                              SessionStart → session-start.sh (new)
  hooks/gate.sh               interpreter lookup, run gate_main.py, else warning JSON
  hooks/session-start.sh      interpreter lookup, run session_main.py, else warning JSON (new)
  hooks/env-guard.sh          unchanged
  lib/gate_main.py            unchanged stub → destructive_guard.hook
  lib/session_main.py         new stub → destructive_guard.session
  lib/check.py                unchanged stub → destructive_guard.check.cli
  lib/destructive_guard/
    config.py                 GateConfig: GATE_ENABLED, GATE_ENV_GUARD, GATE_LOG only
    paths.py                  unchanged
    errors.py                 ConfigError, JevConfigError, UsageError (RulesError, UnparsableError go)
    outcome.py                new: Down (enum), HookOut (decision + warning) and its JSON rendering
    hook.py                   GateHook: the model's `hook` function
    session.py                new: SessionCheck: the model's `sessionStart` function
    log.py                    new: GateLog, one JSON line per call (replaces both logs)
    jev/config.py             JevConfig: key, URL, model, timeout, escalate, prompt
    jev/judge.py              new (replaces decider.py): the model's `judge` function
    jev/client.py             unchanged
    jev/request.py            no scripts/problems; MCP .env check
    jev/prompt.py             `safe` becomes optional
    jev/redactor.py           redact_script removed
    check/{cli,dry_run,report}.py   rewritten on the hook path
  jev/*.json                  unchanged
  formal/SimpleGate.lean      updated in L0
  skills/check/SKILL.md       rewritten in L4
```

Deleted: `engine/`, `shell/`, `scripts/`, `rules/`, `gate/`, `verdict.py`,
`packs/`, `jev/decider.py`, `tests/cases/`, `tests/fixtures/`,
`tests/PORTING.md`.

Size: today `lib/destructive_guard` is ~4 400 lines. About 2 600 go
(`engine` 663, `shell` 433, `scripts` 818, `rules` 361, `gate` 118, parts of
`config.py`, `jev/`, `check/`); the new modules add ~400.

## L0: Lean model matches the decisions; Claude Code assumptions checked

Files: `formal/SimpleGate.lean`, `formal/README` note in the plugin README.

1. `Setting`: remove `off` (D2). `Setting = misconfigured | on`.
2. `Down`: remove `off` and `misconfigured` (misconfigured gives no warning per
   call); add `pythonMissing` and `internalError`. Result:
   `timeout | http | malformed | envReference | badInput | pythonMissing | internalError`.
3. `Call`: add `pythonMissing` and `crash` alongside `tool p` and `badInput`,
   so the wrapper's and the exception path's outputs are part of `hook`:
   `.pythonMissing → ⟨none, some .pythonMissing⟩`,
   `.crash → ⟨none, some .internalError⟩`.
4. `hook … .misconfigured (.tool p) = ⟨.none, none⟩` (D3).
5. New `SessionIssue` (`noKey | badUrl | badPrompt | badValue | pythonMissing`)
   and `sessionStart : Setting → Option SessionIssue`, with the setting
   carrying the issue (`misconfigured (why : SessionIssue)`). New thesis
   **S9** `misconfigured_warns_once`: `sessionStart s = some w ↔ s = .misconfigured w`,
   and `hook` for `.misconfigured _` never warns.
6. S3 becomes "warning **or** misconfigured ⇒ no decision"; S4
   (`fallback_is_claude`) gets the same premise. S1, S2, S5–S8 re-proved; S2's
   right side loses nothing (it already requires `s = .on`).
7. Examples at the bottom extended to one per row of the conformance table in
   L1 (`.misconfigured`, `.pythonMissing`, `.crash`, `.envReference`, risk 0,
   risk = 500, risk 501, each `Down`).
8. **D7 check.** Read the current Claude Code hooks docs (PreToolUse output:
   `permissionDecision`, `systemMessage`; SessionStart output) and record, with
   links and the Claude Code version (`claude --version`):
   - a hook `ask` prompts even when a settings `allow` rule matches;
   - a settings `deny` wins over a hook `ask`;
   - no hook output leaves the call to rules and mode;
   - behaviour under `bypassPermissions` and auto mode;
   - `systemMessage` from PreToolUse and SessionStart is shown to the user.
   Confirm with a throwaway plugin in the scratchpad (hook that always prints
   `ask`, or only a `systemMessage`) against an allow rule, a deny rule,
   bypass mode and auto mode. If an assumption is false, stop and bring it to
   the user: S4/S5 depend on it.
9. `lake build --wfail`: no errors, warnings or `sorry`.

Commit: `Lean gate L0: model with session warning, D2/D3 applied, CC assumptions checked`.

## L1: New hook path (old modules still on disk, no longer used by the hook)

### `outcome.py`

```python
class Down(StrEnum):
    TIMEOUT = "timeout"; HTTP = "http"; MALFORMED = "malformed"
    ENV_REFERENCE = "envReference"; BAD_INPUT = "badInput"
    PYTHON_MISSING = "pythonMissing"; INTERNAL_ERROR = "internalError"

@dataclass(frozen=True)
class HookOut:
    decision: Literal["none", "ask"]          # no "allow"/"deny" in the type
    reason: str | None = None                 # set iff decision == "ask"
    warning: Down | None = None
    detail: str | None = None                 # e.g. "http 503", "timeout after 1500 ms"

    def to_json(self) -> str | None: ...      # ask → hookSpecificOutput; warning → {"systemMessage": "destructive-guard: …"}; else None
```

Warning texts (one line each, all start with `destructive-guard:`):
`Jev did not answer in time (1500 ms); Claude Code's permissions apply`,
`Jev returned http 503; …`, `Jev's answer was malformed; …`,
`call mentions a .env file and was not sent to Jev; …`,
`could not read the hook input; …`, `no Python >= 3.14 found (set GATE_INFRA_PYTHON); …`,
`internal error: <type>; …`.

Constructing a `HookOut` with a warning and `decision="ask"` raises
(`__post_init__`), which is S3 in code.

### `jev/judge.py`

```python
class JevJudge:
    @staticmethod
    def risk(probs, prompt) -> float            # sum of the prompt's `ask` choices
    @classmethod
    def judge(cls, result: dict, cfg) -> HookOut:
        # {error: "timeout"|"http 503"|"malformed"|"network"} → HookOut("none", warning=…)
        # ("network" maps to Down.HTTP with detail "network")
        # probabilities → risk > escalate ? ask("jev: <top> p=… risk=…") : none
```

Reason format stays `jev: destructive p=0.81 risk=0.86` (same `_fmt`/`_top_of`
as `decider.py`, moved here). `decider.py` is deleted in L2.

### `jev/config.py`

- Remove the `GATE_JEV` toggle, `allowThreshold`, `canLift`, `scope`,
  `logPath`.
- `read(env)` always returns a config or raises `JevConfigError` (no `None`):
  missing `TYPESAFE_API_KEY`, invalid URL/timeout/threshold/prompt.
- `JevConfigError` carries a `SessionIssue`-like `kind` (`noKey`, `badUrl`,
  `badPrompt`, `badValue`) for the session warning.

### `jev/request.py`

- `build_state(call)`: Bash → `{tool, command, notes}` (no `scripts`); MCP →
  first `Redactor.references_env_file(json.dumps(input))` → `None` (D9), else
  as today.
- Remove `scripts_payload`, `problem_notes`, `MAX_SCRIPTS_BYTES`.

### `hook.py` (the model's `hook`)

```text
main(stdin, env):
  try:
    gate = GateConfig.read(env)            # GATE_ENABLED, GATE_LOG; bad value → misconfigured (silent)
    if not gate.enabled: return 0          # gate.sh already exits before Python; kept for check/tests
    try: cfg = JevConfig.read(env)
    except JevConfigError: log(misconfigured); return 0         # S9: silent per call
    try: input = parse(stdin)              # JSON object with tool_name str
    except: out = HookOut(none, warning=BAD_INPUT)
    else:
      call = Call.from_input(input)        # Bash with str command | mcp__* | other → nothing to do
      if call is None: return 0
      state = JevRequest.build_state(call)
      if state is None: out = HookOut(none, warning=ENV_REFERENCE)
      else: out = JevJudge.judge(JevClient().ask_jev(state, cfg), cfg)
  except Exception as e:
    out = HookOut(none, warning=INTERNAL_ERROR, detail=type(e).__name__)
  write out.to_json(); GateLog.write(...); return 0
```

- The `.env` check runs on the raw payload before redaction; nothing
  unredacted reaches `JevClient` (S7).
- `GATE_DONE_FILE` handling removed.
- A non-Bash, non-MCP tool (should not happen given the matcher) gives no
  output and no request.

### `log.py` (`GATE_LOG`, replaces `GATE_JEV_LOG`)

One JSON line per handled call, best-effort, never fails the hook:
`ts, tool, command|input (redacted; null on .env), probabilities, risk,
decision (ask|none), reason, warning, usage, latencyMs`. Misconfigured calls
log `warning: null, misconfigured: "<kind>"` so the log explains silent calls.

### `hooks/gate.sh`

```bash
dir="$(dirname "$0")"
case "$(printf '%s' "${GATE_ENABLED:-}" | tr '[:upper:]' '[:lower:]')" in 0|false|no|off) exit 0 ;; esac
warn() { printf '{"systemMessage":"destructive-guard: %s"}' "$1"; exit 0; }
py="${GATE_INFRA_PYTHON:-}"
[ -n "$py" ] || py="$(command -v python3.14 || command -v python3)"
[ -n "$py" ] || warn "no Python >= 3.14 found (set GATE_INFRA_PYTHON); Claude Code's permissions apply"
out="$("$py" -I "$dir/../lib/gate_main.py" 2>/dev/null)"; rc=$?
{ [ "$rc" -eq 127 ] || [ "$rc" -eq 126 ] || [ "$rc" -eq 3 ]; } && warn "no Python >= 3.14 found …"
[ "$rc" -ne 0 ] && warn "internal error (engine exit $rc); Claude Code's permissions apply"
[ -n "$out" ] && printf '%s' "$out"
exit 0
```

A partial stdout with a non-zero exit is discarded (the warning replaces it),
so a crashed engine can never leave half an `ask` or anything else behind.

### `SessionStart` (D3, S9)

- `hooks/hooks.json`: add `"SessionStart": [{"hooks": [{"type": "command",
  "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh\""}]}]`.
- `hooks/session-start.sh`: same interpreter lookup as `gate.sh`; Python
  missing → the `pythonMissing` warning (this is where the user learns it once);
  runs `lib/session_main.py`.
- `lib/session_main.py`: version stub like `gate_main.py`.
- `lib/destructive_guard/session.py` `SessionCheck.main(env)`:
  gate disabled → nothing; `JevConfig.read` fails → one `systemMessage`
  naming the problem (`TYPESAFE_API_KEY is not set: destructive-guard only
  blocks .env files this session`); removed 0.8 variables set
  (`GATE_CHECKS`, `GATE_RULES_FILE`, `GATE_RULES`, `GATE_DISABLE_RULES`,
  `GATE_STRICT`, `GATE_JEV`, `GATE_JEV_ALLOW_THRESHOLD`, `GATE_JEV_CAN_LIFT`,
  `GATE_JEV_SCOPE`, `GATE_JEV_LOG`) → one line listing them as ignored. Both
  in one message. Never contacts Jev.

### Tests (new)

- `tests/test_lean_conformance.py`: drives the real `gate.sh` (via
  `testkit.HookRunner`) with `JevMock` over
  {misconfigured (no key, bad URL), on} × {bad stdin, Bash `.env` call, MCP
  `.env` call, clean Bash, clean MCP, non-gated tool} × {timeout, HTTP 500,
  429 over budget, malformed body, risk 0, risk = escalate, risk > escalate}
  plus {no Python, Python 3.9, engine exit 1 with partial stdout, engine
  exception}. For each output it asserts:
  - S1: never `allow`/`deny`, never `"continue": false`;
  - S2: `ask` iff on ∧ not `.env` ∧ answered ∧ risk > escalate;
  - S3: a `systemMessage` never comes with a `permissionDecision`;
  - S8: an answered call never warns;
  - S9: misconfigured → no output at all at `PreToolUse`;
  - S7: the mock never receives a body containing `.env` or an unredacted
    secret from the corpus (`TOKEN=abc…`, `Bearer …`, URL credentials).
  Each Lean `example` has a test with the same name.
- `tests/test_session_start.py`: no key, bad URL, bad prompt file, removed
  variables, all fine (no output), gate disabled, no Python.
- `tests/test_outcome.py`: `HookOut` JSON bytes for ask / warning / none;
  ask + warning raises.
- `tests/test_jev_judge.py`: thresholds, tie → last choice, error mapping.
- Hook latency: `testkit/bench_gate.py` rewritten to time the misconfigured
  path (no network); assert median < 100 ms on CI is too flaky, so it stays a
  manual benchmark and the result goes into the L6 commit message.

### Tests (adapted in L1)

`testkit/hook.py` `HookRunner.run`: the isolated env clears `GATE_JEV`,
`TYPESAFE_API_KEY`, `GATE_JEV_LOG` and every `GATE_JEV_*`; Jev tests pass the
mock URL and a key explicitly. Old rule tests are left alone in L1 (they still
run against modules that exist) except those that assert hook output:
`test_gate_hook.py`, `test_gate_hook_jev.py`, `test_jev_http.py`,
`test_gate_sh_lookup.py`, `test_config.py::test_hook_*`. Those move to the new
expectations or are deleted with the rules in L2 (listed there).

Commit: `Lean gate L1: Jev-only hook, session warning, conformance tests`.

## L2: Delete the rule gate

Delete:

- `lib/destructive_guard/{engine,shell,scripts,rules,gate}/`, `verdict.py`,
  `jev/decider.py`, `packs/`.
- From `errors.py`: `RulesError`, `UnparsableError`.
- From `config.py`: everything except `enabled`, `envGuard`, `log` and
  `ProjectDir` resolution; `available_packs`, `build_rules`, `_read_checks`
  go.
- From `jev/redactor.py`: `redact_script` (and `_drop_env_lines` if MCP no
  longer needs it after D9).
- From `jev/prompt.py`: `safe` becomes optional (validated if present, unused
  by the decision); the built-in prompts keep it for the log.
- Tests: `test_corpus.py`, `test_packs.py`, `test_rule_kinds.py`,
  `test_rules_loading.py`, `test_tokenizer.py`, `test_gate_engine.py`,
  `test_gate_scripts.py`, `test_gate_fn.py`, `tests/cases/`,
  `tests/fixtures/`, `tests/PORTING.md`.
- Tests trimmed to what still exists: `test_gate_hook.py` (registration,
  exact bytes, non-UTF-8 stdin), `test_gate_hook_jev.py` and `test_jev_http.py`
  (merge into one file on the new hook: request shape, retries, timeouts,
  redacted MCP payload, audit log), `test_jev_units.py` (drop scope/can-lift/
  allow-threshold/scripts cases), `test_jev_request_py.py` (drop
  `test_failures_keep_rule_result_*`, `test_can_lift_0_mcp`,
  `test_undecided_keeps_rule_result`, scripts payload), `test_config.py` (three
  variables + env guard), `test_gate_sh_lookup.py` (warnings instead of asks).
- Repo-level: `tests/test_porting.py` drops `DG` from `PLUGIN_DIRS` (the
  porting record goes with the code it recorded); `tests/test_testkit_contract.py`
  uses another variable than `GATE_CHECKS` in its examples;
  `tests/test_one_class_per_file.py` keeps working (check the listed dirs).
- `testkit/`: delete `porting.py` only if `test_porting.py` no longer needs
  it for GD (it does: keep); delete `projects.py` if nothing imports it after
  the script tests are gone; `stubs.py` (its `STUBS` list now also has the
  workflow's `flow.py`) gains `session_main.py`, and `pyproject.toml`'s
  per-file ignores for `lib/{check,gate_main}.py` gain `session_main`.
- `pyproject.toml`: no path changes expected; re-run ruff.

Acceptance:

```bash
grep -rnE "GATE_CHECKS|GATE_STRICT|GATE_RULES|GATE_DISABLE_RULES|CAN_LIFT|ALLOW_THRESHOLD|JEV_SCOPE|GATE_JEV_LOG|gate-config:|unparsable:|GATE_DONE_FILE" plugins tests testkit
```

returns only `session.py`'s removed-variable list, its test and the README
migration section.

Commit: `Lean gate L2: remove rules, shell parser and script scan`.

## L3: Lean ↔ code traceability

Small, separate so it can be reviewed on its own:

- A table at the top of `hook.py`, `jev/judge.py`, `session.py` naming the Lean
  definition each function implements (`hook`, `judge`, `sessionStart`).
- `tests/test_lean_conformance.py` reads the `example` lines from
  `SimpleGate.lean` and fails if an example has no test of the same name (keeps
  model and tests from drifting without needing Lean in the Python CI job).

Commit: `Lean gate L3: model ↔ code cross-references`.

## L4: `check` skill on the hook path (D5)

- `check/dry_run.py`: `effective_config()` → `{enabled, envGuard, log, jev:
  {url, model, timeoutMs, escalateThreshold, prompt, question, ask, apiKey:
  "[set]"|"[missing]"}, sessionWarnings: [...]}`. `check_call()` builds the
  same hook input and calls the hook's decision function in-process (not
  `gate.sh`), returning `{decision, reason, risk, top, warning}`.
- `check/cli.py`: options `--json`, `--config`, `--mcp`; remove `--jev` and
  `--cwd` (no scripts are read any more). Passing `--jev` gives a usage error
  that says it is no longer needed.
- `check/report.py`: text output

  ```text
  Bash: git push --force origin main
  decision: ask
  reason:   jev: destructive p=0.81 risk=0.86
  ```

  or `decision: none (risk 0.04 ≤ 0.5)` or `decision: none — warning: Jev did not answer …`.
- `skills/check/SKILL.md`: every call check sends the redacted call to Jev and
  costs a request; never put secrets in the checked call; a `.env` mention is
  reported as "not sent".
- Tests: `test_check.py` rewritten with `JevMock`; documented invocations must
  pass the gate (the check command line itself mentions no `.env`).

Commit: `Lean gate L4: check skill on Jev`.

## L5: `gated-dev-simple-workflow` follow-up (D6)

- `agents/ticket-planner.md`: `## Gated operations` columns `Command`, `Gate`,
  `Reason`. `Gate` = `ask (risk 0.86)` from `GATE_CHECK`, or `unknown`. The
  planner always lists calls it judges risky itself; `GATE_CHECK` only fills
  the `Gate` column.
- `skills/ticket/SKILL.md` step 3: set `GATE_CHECK` only when
  `.claude/gated-dev.json` has `"dryRunGate": true`; drop "Never pass `--jev`"
  and `--cwd`.
- `skills/ticket/references/config.md`: document `dryRunGate` next to
  `tracker` and `flow` (default false; each checked call is a Jev request that
  sends the redacted command). `/ticket-flow` runs `/ticket` sessions, so it
  inherits the setting; nothing in `scripts/gated_dev/flow/` calls the gate.
- `README.md` of the workflow: replace the `Rule ID` paragraphs and the
  "If `destructive-guard` moves to the Jev-only design" note.
- `tests/test_watch_pr.py::test_watcher_command_passes_the_gate`: run the
  watcher command through the new hook with `JevMock` answering safe; assert
  no `ask`.
- Version bump of the workflow plugin (`plugin.json` + catalog).

Commit: `gated-dev: gated operations without rule ids`.

## L6: Docs and release

- `plugins/destructive-guard/README.md` rewrite:
  - what it does: Jev asks before risky Bash/MCP calls; `.env` files are
    blocked for Read/Edit/Write; it never allows or denies;
  - what it no longer does: no rules, no parser, no fail-closed; without a key
    it only blocks `.env` files and says so once per session;
  - every warning and what to do about it;
  - env table (kept variables only), what is sent, the question, prompts;
  - Claude Code assumptions from L0 with links and version;
  - known blind spots: scripts a command runs (D4), `.env` calls are never
    judged;
  - migration from 0.8: removed variables, behaviour changes table;
  - "Design decisions and history" section: origin, Python port, class
    refactor, Lean model, this redesign (PR #9 has the earlier summaries:
    merge or copy them first).
- `test_readme.py`: every env name in `lib/` and `hooks/` documented; every
  `jev/*.json` prompt documented; the pack check goes.
- `CLAUDE.md`: the `destructive-guard` section (Jev-only, fail-open with
  warnings, SessionStart hook, model location, conformance test); the
  "Main vars" list.
- Versions: `destructive-guard` `0.8.x` → `1.0.0` with a new description in
  `plugin.json` and the catalog; bump `metadata.version`.
- `docs/plans/lean-gate.md`: summarised into the README and deleted.
- Manual trial in a real session before tagging: Jev on, Jev with a wrong key,
  no key, Jev endpoint unreachable (D10 noise check), `bypassPermissions`.
- `claude plugin validate .`, `jq . .claude-plugin/marketplace.json`,
  `uv run pytest`, `uv run ruff check .`, `lake build --wfail`.

Commit: `destructive-guard 1.0.0: lean gate`.

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
- **Blind spots.** Scripts (D4), `.env`-mentioning calls, and all calls while
  Jev is down are judged only by Claude Code's own permissions.
