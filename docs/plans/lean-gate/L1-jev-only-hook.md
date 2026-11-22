# L1: Jev-only hook, session warning, conformance tests

> Part of the [lean gate plan](README.md). Depends on: L0 (theses to test against), LJ0 (`testkit/live_jev.py`). Not blocked: D1, D2, D4 (final: no parser, no scripts) and D12 were answered on 2026-11-22.

## `outcome.py`

```python
class Down(StrEnum):
    TIMEOUT = "timeout"; HTTP = "http"; NETWORK = "network"; MALFORMED = "malformed"
    ENV_REFERENCE = "envReference"; BAD_INPUT = "badInput"
    PYTHON_MISSING = "pythonMissing"; INTERNAL_ERROR = "internalError"

    @property
    def jev_unavailable(self) -> bool:        # the model's Down.jevUnavailable
        return self in (Down.TIMEOUT, Down.HTTP, Down.NETWORK, Down.MALFORMED)

    @property
    def plugin_fault(self) -> bool:           # D12: asks with a warning
        return self in (Down.BAD_INPUT, Down.PYTHON_MISSING, Down.INTERNAL_ERROR)

@dataclass(frozen=True)
class HookOut:
    decision: Literal["none", "ask"]          # no "allow"/"deny" in the type
    reason: str | None = None                 # set iff decision == "ask"
    warning: Down | None = None
    detail: str | None = None                 # e.g. "http 503", "timeout after 1500 ms"

    @classmethod
    def fault(cls, kind: Down, detail: str | None = None) -> "HookOut": ...
    # plugin fault (D12) → ask with reason "plugin-fault: <text>" and a warning

    def to_json(self) -> str | None: ...
    # ask            → {"hookSpecificOutput": {…"permissionDecision": "ask", "permissionDecisionReason": reason}}
    # ask + warning  → the same plus "systemMessage": "destructive-guard: …"   (D11, D12)
    # warning only   → {"systemMessage": "destructive-guard: …"}
    # neither        → None (no output)
```

`__post_init__` enforces S3: `ask` with a warning only when
`warning.jev_unavailable or warning.plugin_fault`; such a warning only with `ask`.

Texts (one line each, all start with `destructive-guard:`):

| Case | Ask reason | `systemMessage` |
| --- | --- | --- |
| timeout | `jev-unavailable: timeout after 1500 ms` | `Jev did not answer in time (1500 ms); asking you instead. GATE_ENABLED=0 turns the gate off.` |
| HTTP | `jev-unavailable: http 503` | `Jev returned http 503; asking you instead. …` |
| network | `jev-unavailable: network error` | `Jev could not be reached; asking you instead. …` |
| malformed | `jev-unavailable: malformed answer` | `Jev's answer was malformed; asking you instead. …` |
| `.env` | none | `call mentions a .env file and was not sent to Jev; Claude Code's permissions apply` |
| bad input | `plugin-fault: bad hook input` | `could not read the hook input; asking you instead. GATE_ENABLED=0 turns the gate off.` |
| no Python | `plugin-fault: no Python >= 3.14 found (set GATE_INFRA_PYTHON)` | `no Python >= 3.14 found (set GATE_INFRA_PYTHON); asking you instead. GATE_ENABLED=0 turns the gate off.` |
| internal error | `plugin-fault: internal error: <type>` | `internal error (<type>); asking you instead. GATE_ENABLED=0 turns the gate off.` |

## `jev/judge.py`

```python
class JevJudge:
    @staticmethod
    def risk(probs, prompt) -> float            # sum of the prompt's `ask` choices
    @classmethod
    def judge(cls, result: dict, cfg) -> HookOut:
        # {error: "timeout"|"http 503"|"network"|"malformed"}
        #     → HookOut("ask", reason="jev-unavailable: …", warning=Down.…, detail=…)   (D11)
        # probabilities → risk > escalate ? ask("jev: <top> p=… risk=…") : none
```

Reason format stays `jev: destructive p=0.81 risk=0.86` (same `_fmt`/`_top_of`
as `decider.py`, moved here). `decider.py` is deleted in L2.

## `jev/config.py`

- Remove the `GATE_JEV` toggle, `allowThreshold`, `canLift`, `scope`,
  `logPath`.
- `read(env)` always returns a config or raises `JevConfigError` (no `None`):
  missing `TYPESAFE_API_KEY`, invalid URL/timeout/threshold/prompt.
- `JevConfigError` carries a `SessionIssue`-like `kind` (`noKey`, `badUrl`,
  `badPrompt`, `badValue`) for the session warning.

## `jev/request.py`

- `build_state(call)`: Bash → `{tool, command, notes}` (no `scripts`; the
  command text goes to Jev as it is, redacted, nothing is parsed, D4); MCP →
  first `Redactor.references_env_file(json.dumps(input))` → `None` (D9), else
  as today.
- Remove `scripts_payload`, `problem_notes`, `MAX_SCRIPTS_BYTES`. The hook no
  longer imports `shell/`, `scripts/` or `redact_script`; their deletion is L2.
  There is no parse-error case and no `unparsable:` ask.

## `hook.py` (the model's `hook`)

```text
main(stdin, env):
  try:
    gate = GateConfig.read(env)            # GATE_ENABLED, GATE_LOG; bad value → misconfigured (silent)
    if not gate.enabled: return 0          # gate.sh already exits before Python; kept for check/tests
    try: cfg = JevConfig.read(env)
    except JevConfigError: log(misconfigured); return 0         # S9: silent per call
    try: input = parse(stdin)              # JSON object with tool_name str
    except: out = HookOut.fault(BAD_INPUT, "bad hook input")
    else:
      call = Call.from_input(input)        # Bash with str command | mcp__* | other → nothing to do
      if call is None: return 0
      state = JevRequest.build_state(call)
      if state is None: out = HookOut(none, warning=ENV_REFERENCE)
      else: out = JevJudge.judge(JevClient().ask_jev(state, cfg), cfg)
  except Exception as e:
    out = HookOut.fault(INTERNAL_ERROR, detail=type(e).__name__)
  write out.to_json(); GateLog.write(...); return 0
```

- The `.env` check runs on the raw payload before redaction; nothing
  unredacted reaches `JevClient` (S7).
- `GATE_DONE_FILE` handling removed.
- A non-Bash, non-MCP tool (should not happen given the matcher) gives no
  output and no request.

## `log.py` (`GATE_LOG`, replaces `GATE_JEV_LOG`)

One JSON line per handled call, best-effort, never fails the hook:
`ts, tool, command|input (redacted; null on .env), probabilities, risk,
decision (ask|none), reason, warning, usage, latencyMs`. Misconfigured calls
log `warning: null, misconfigured: "<kind>"` so the log explains silent calls.

## `hooks/gate.sh`

```bash
dir="$(dirname "$0")"
case "$(printf '%s' "${GATE_ENABLED:-}" | tr '[:upper:]' '[:lower:]')" in 0|false|no|off) exit 0 ;; esac
fault() { printf '{"systemMessage":"destructive-guard: %s; asking you instead. GATE_ENABLED=0 turns the gate off.","hookSpecificOutput":{"permissionDecision":"ask","permissionDecisionReason":"plugin-fault: %s"}}' "$1" "$1"; exit 0; }
py="${GATE_INFRA_PYTHON:-}"
[ -n "$py" ] || py="$(command -v python3.14 || command -v python3)"
[ -n "$py" ] || fault "no Python >= 3.14 found (set GATE_INFRA_PYTHON)"
out="$("$py" -I "$dir/../lib/gate_main.py" 2>/dev/null)"; rc=$?
{ [ "$rc" -eq 127 ] || [ "$rc" -eq 126 ] || [ "$rc" -eq 3 ]; } && fault "no Python >= 3.14 found (set GATE_INFRA_PYTHON)"
[ "$rc" -ne 0 ] && fault "internal error (engine exit $rc)"
[ -n "$out" ] && printf '%s' "$out"
exit 0
```

`gate.sh` asks by itself on a plugin fault (D12), so it needs no Python for
that. A partial stdout with a non-zero exit is discarded (the fault ask
replaces it), so a crashed engine can never leave half an `ask` or anything
else behind.

## `SessionStart` (D3, S9)

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

## Tests (new)

- `tests/test_lean_conformance.py`: drives the real `gate.sh` (via
  `testkit.HookRunner`) with `JevMock` over
  {misconfigured (no key, bad URL), on} × {bad stdin, Bash `.env` call, MCP
  `.env` call, clean Bash, clean MCP, non-gated tool} × {timeout, HTTP 500,
  429 over budget, malformed body, risk 0, risk = escalate, risk > escalate}
  plus {no Python, Python 3.9, engine exit 1 with partial stdout, engine
  exception}. For each output it asserts:
  - S1: never `allow`/`deny`, never `"continue": false`;
  - S2: `ask` iff on ∧ not `.env` ∧ (answered with risk > escalate ∨ Jev
    unavailable ∨ plugin fault);
  - S3: a `systemMessage` comes with `ask` exactly for timeout, HTTP (500, 429
    over budget), network, malformed, bad stdin, no Python and engine
    exception; the `.env` `systemMessage` comes without a `permissionDecision`;
  - S10: with a key set, a sent call never gets empty output when the mock
    hangs, refuses the connection, returns 5xx or returns garbage;
  - S8: an answered call never warns;
  - S9: misconfigured → no output at all at `PreToolUse`;
  - S7: the mock never receives a body containing `.env` or an unredacted
    secret from the corpus (`TOKEN=abc…`, `Bearer …`, URL credentials).
  Each Lean `example` has a test with the same name.
- `tests/test_session_start.py`: no key, bad URL, bad prompt file, removed
  variables, all fine (no output), gate disabled, no Python.
- `tests/test_outcome.py`: `HookOut` JSON bytes for ask / ask + warning /
  warning / none; ask with a warning that is neither Jev-unavailable nor a
  plugin fault raises; a Jev or plugin-fault warning without ask raises.
- `tests/test_jev_judge.py`: thresholds, tie → last choice, each error →
  ask + warning with the right reason.
- Hook latency: `testkit/bench_gate.py` rewritten to time the misconfigured
  path (no network); assert median < 100 ms on CI is too flaky, so it stays a
  manual benchmark and the result goes into the L6 commit message.

## Tests (adapted in L1)

`testkit/hook.py` `HookRunner.run`: the isolated env clears `GATE_JEV`,
`TYPESAFE_API_KEY`, `GATE_JEV_LOG` and every `GATE_JEV_*`; Jev tests pass the
mock URL and a key explicitly. Old rule tests are left alone in L1 (they still
run against modules that exist) except those that assert hook output:
`test_gate_hook.py`, `test_gate_hook_jev.py`, `test_jev_http.py`,
`test_gate_sh_lookup.py`, `test_config.py::test_hook_*`. Those move to the new
expectations or are deleted with the rules in L2 (listed there).

Commit: `Lean gate L1: Jev-only hook, session warning, conformance tests`.

## LJ1: live hook tests

Part of the L1 commit. `tests/live/test_jev_live_hook.py`, through `testkit.HookRunner` and the real
`gate.sh`:

- A clear-cut `ask` case and a clear-cut `none` case give exactly the hook
  output the conformance test expects (`permissionDecision: "ask"` with a
  `jev:` reason / empty stdout).
- **D11 for real:** wrong key → `ask` with `jev-unavailable: http 401` and the
  warning; `GATE_JEV_TIMEOUT_MS=1` → `ask` with `jev-unavailable: timeout …`.
- Misconfigured (no key) → empty stdout and no request (the counter does not
  move); the `SessionStart` hook prints its one warning.
- `.env` call → warning, no request.
- `GATE_LOG` lines for these calls contain the redacted command, the
  probabilities and the decision, and never the key (grep the log for it).

## Done when

- [ ] `uv run pytest` and `uv run ruff check .` pass
- [ ] `claude plugin validate .` and `jq . .claude-plugin/marketplace.json` pass
- [ ] `cd plugins/destructive-guard/formal && PATH="$HOME/.elan/bin:$PATH" lake build --wfail` passes
- [ ] one commit with the message given above; nothing pushed unless asked
