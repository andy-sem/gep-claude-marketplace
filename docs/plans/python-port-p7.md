# Python Port P7 (destructive-guard `gate_jev`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P7 is **one package** (one commit). Tasks 1–4 do not commit; Task 5 commits.
> Written ahead of P2–P6 landing: before starting, re-check names and counts against the committed tests and adjust this file.

**Goal:** `destructive_guard.gate_jev`: Jev configuration (`GATE_JEV_*`), prompts (built-in `jev/*.json`, file prompts, env overrides, validation), redaction (commands, scripts, MCP inputs, SQL literals, `.env` lines), the request (`urllib.request`, one overall time budget, retries with `retry-after`), the decision (`jev_decision`, uncertain band, `canLift`) and the audit log. The P2 `test_jev_units.py` and the prompt bridge parts of P1 `test_jev_prompt.py` are retargeted; the HTTP rows (`test_jev_http.py`, `test_gate_hook_jev.py`) stay contract tests and turn green on Python at P9.

**Architecture:** pure parts first (config, prompts, redaction, decision), then the request with an injectable `opener` (the Python twin of JS `fetchImpl`) so unit tests use a fake opener, and the existing local `JevMock` server covers real HTTP. The module is imported lazily by `gate()` only when `GATE_JEV` is set (latency).

**Tech Stack:** Python ≥ 3.14 stdlib (`urllib.request`, `urllib.error`, `json`, `time`, `re`, `email.utils` for HTTP-date `retry-after`), pytest, `testkit.jev_mock`.

**Spec:** `lib/gate-jev.mjs`; `jev/*.json`; tests `tests/test_jev_units.py`, `tests/test_jev_http.py`, `tests/test_jev_prompt.py`, `tests/test_gate_hook_jev.py`; README §Jev.

**Paths** are relative to `plugins/destructive-guard/` unless they start with `docs/` or `testkit/`.

## Global Constraints

- Conventions of `docs/plans/python-port-p4.md` §Conventions.
- No change to `lib/*.mjs`, `hooks/*`, `packs/`, `jev/`, JS tests; node suites green (735 / 68).
- Never send a call that references an `.env` file; never log or print the API key (`TYPESAFE_API_KEY`); loopback-only `http://` URLs, otherwise `https://` (as `LOOPBACK` in JS).
- `ask_jev` never raises: every failure is `{"error": ..., "latencyMs": ...}`.
- Exit criterion: `test_jev_units.py` has no bridge; a new `test_jev_request_py.py` drives `ask_jev`/`run_jev` against `JevMock` in-process and mirrors every `test_jev_http.py` row; `uv run pytest` green.

## Review Focus

- Time budget: total wall time ≤ `GATE_JEV_TIMEOUT_MS` (max 30000) including retries and `retry-after` sleeps; a `retry-after` beyond the budget gives up at once (one hit).
- Redaction parity: the 9 `redact` rows + script/MCP rows; secret-name regex is case-insensitive; SQL keys `query`/`sql`/`statement` get literal redaction; truncation limits (`MAX_COMMAND_CHARS`, `MAX_INPUT_CHARS`, `MAX_SCRIPTS_BYTES`) with the same notes.
- Request body bytes: same JSON fields and order as JS (`model`, `state`, `questions`); the mock asserts content, not order, but the audit log and payload size depend on it.
- Malformed response (missing `answers`, a status answer without a code) → `fallback: malformed`, never a crash.

---

### Task 1: Configuration and prompts

**Files:** Create `lib/destructive_guard/gate_jev.py`. Modify `tests/test_jev_units.py`, `tests/test_jev_prompt.py` (bridge parts only).

**Interfaces (Produces):** `JEV_URL`, `DEFAULT_PROMPT = "destructive"`, `SCOPES = ["bash", "mcp"]`, `JevConfigError`, `read_jev_config(env, *, cwd=None) -> dict | None`, `validate_prompt(p, where="prompt") -> dict`, `builtin_prompt(name) -> dict`, `prompt_from_env(env) -> dict`.

- [ ] **Step 1:** Retarget the `readJevConfig` and prompt rows → fail → port → pass.

### Task 2: Redaction

**Interfaces (Produces):** `references_env_file(command) -> bool`, `redact(command) -> str | None`, `redact_script(text) -> str`, `redact_mcp_input(tool_input) -> str`.

- [ ] **Step 1:** Retarget the `redact`/`redactScript`/`redactMcpInput` rows → fail → port → pass.

### Task 3: State, answer parsing, decision

**Interfaces (Produces):** `build_state(call: dict) -> dict | None`, `parse_answer(json, prompt=None) -> dict | None`, `jev_decision(probs, cfg) -> dict | None`; internal `request_body`, `scripts_payload`, `problem_notes`.

- [ ] **Step 1:** Retarget `buildState`, `parseAnswer`, `jevDecision` rows → fail → port → pass.

### Task 4: Request, `run_jev`, audit

**Files:** Modify `lib/destructive_guard/gate_jev.py`. Create `tests/test_jev_request_py.py`.

**Interfaces (Produces):** `ask_jev(state, cfg, *, opener=urllib.request.urlopen, sleep=time.sleep, clock=time.monotonic) -> dict`, `run_jev(call, rule_result, cfg, *, opener=..., ...) -> dict | None`; internal `retry_delay`, `audit`.

- [ ] **Step 1:** `test_jev_request_py.py`: one test per `test_jev_http.py` row, same `JevMock` setups, calling `run_jev` directly (rule result and call built as the hook would); plus `test_ask_jev_never_raises` with an opener that raises each `urllib` error type.
- [ ] **Step 2:** Run → fail → port → pass.

### Task 5: Verify, commit

- [ ] **Step 1:** Node suites (735 / 68), `uv run pytest`, `uv run ruff check .`; report `GD_IMPL=py` failure count.
- [ ] **Step 2:** `docs/plans/python-port.md` §4: mark P7 done (link this file).
- [ ] **Step 3:** One commit by file name, `Python port P7: destructive_guard gate_jev`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
