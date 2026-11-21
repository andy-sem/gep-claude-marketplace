# Python Port P8 (destructive-guard `gate`, `check` CLI, hook entry) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P8 is **one package** (one commit). Tasks 1–5 do not commit; Task 6 commits.
> Written ahead of P2–P7 landing: before starting, re-check names and counts against the committed tests and adjust this file.

**Goal:** the last Python pieces of `destructive-guard`: `gate()` (rules + script scan + Jev), the hook entry `gate_main.main()` (stdin JSON → decision on stdout, `GATE_LOG`, done-file protocol), and the `check` CLI (`check.main()`: command / `--mcp` / `--config` / `--json` / `--cwd` / `--jev`). After P8 the whole suite passes with `GD_IMPL=py` **except** the `gate.sh` tests, which still start node until P9. Latency is measured.

**Architecture:** replace the P0 placeholders `lib/destructive_guard/gate_main.py` and `lib/destructive_guard/check.py`; the version-check stubs `lib/gate_main.py` / `lib/check.py` stay unchanged. To run the hook contract tests on Python before `gate.sh` switches, the test kit gets a way to run the Python engine *behind* the same done-file protocol: `testkit/_gate_py.sh`, a copy of `gate.sh` that starts `python -I lib/gate_main.py` (test-only, deleted in P9).

**Tech Stack:** Python ≥ 3.14 stdlib, pytest, `testkit`.

**Spec:** `lib/gate-engine.mjs` (`gate`, `logDecision`, `main`, `emit`, `applyJev`), `lib/check.mjs`; tests `tests/test_check.py`, `tests/test_gate_hook.py`, `tests/test_gate_hook_jev.py`, `tests/test_jev_http.py`, `tests/test_config.py` (hook rows); README §Check, §Logging; Review Focus of `docs/plans/python-port.md`.

**Paths** are relative to `plugins/destructive-guard/` unless they start with `docs/` or `testkit/`.

## Global Constraints

- Conventions of `docs/plans/python-port-p4.md` §Conventions.
- No change to `lib/*.mjs`, `hooks/*`, `packs/`, `jev/`, JS tests; node suites green (735 / 68).
- Output bytes identical to JS: ask JSON without a trailing newline (as `emit` writes it), empty stdout for "no opinion"; `check --json` parsed-equal, text output line-equal.
- Exit criterion: `GD_IMPL=py uv run pytest plugins/destructive-guard/tests` green except tests that go through `hooks/gate.sh` (listed in the commit body); with `GATE_HOOK_IMPL=py-direct` (Task 1) those pass too.

## Review Focus

- Fail-closed: any exception in `main` → `gate-config: internal error: …` ask; done-file written only after the decision is on stdout; `GATE_ENABLED=0` emits nothing even with broken input or config.
- Invalid UTF-8 on stdin: read bytes, decode with `errors="replace"` (pinned in P1), never crash-allow.
- Startup cost: `gate_jev` and `gate_scripts` imported lazily (scripts only for Bash, Jev only with `GATE_JEV`); no pack JSON read when disabled.
- Latency: p50/p95 of a full hook call, JS vs Python, 200 calls each on a mixed command set; Python p95 no slower than JS by more than ~50 ms. If it is, profile import time (`-X importtime`) before optimising.

---

### Task 1: Test kit — Python engine behind the wrapper

**Files:** Create `testkit/_gate_py.sh`. Modify `testkit/impl.py`, `tests/test_testkit_impl.py`.

**Interfaces (Produces):** `Impl.gate_hook()` returns `["bash", "testkit/_gate_py.sh"]` when `name == "py"` and env `GATE_HOOK_IMPL=py-direct` is set; otherwise unchanged (`hooks/gate.sh`). `_gate_py.sh` = `gate.sh` with the node line replaced by the D1a lookup and `-I "$dir/../lib/gate_main.py"`, exit 3 → `python unavailable`.

- [ ] **Step 1:** Test `test_gate_py_wrapper_asks_without_python` (`GATE_INFRA_PYTHON=/nope` → ask `unparsable: python unavailable`). Implement. Pass.

### Task 2: `gate()` and `apply_jev`

**Files:** Modify `lib/destructive_guard/gate_engine.py`.

**Interfaces (Produces):** `gate(input, rules, *, env, cwd=None, strict=True, trace: dict | None = None) -> dict | None`; internal `apply_jev(input, result, rules, collected, env)`.

- [ ] **Step 1:** Unit tests in `tests/test_gate_fn.py`: closed results skip the scan; Bash with no rule result scans scripts; `GATE_JEV` set collects scripts even with a rule result; a scan exception → `gate-config: script scan failed: …`. Fail → port → pass.

### Task 3: Hook entry

**Files:** Replace `lib/destructive_guard/gate_main.py`.

**Interfaces (Produces):** `main(stdin: BinaryIO = sys.stdin.buffer, env: Mapping = os.environ) -> int` (always 0; writes `GATE_DONE_FILE`); internal `emit`, `log_decision`.

- [ ] **Step 1:** Run `GD_IMPL=py GATE_HOOK_IMPL=py-direct uv run pytest plugins/destructive-guard/tests/test_gate_hook.py plugins/destructive-guard/tests/test_config.py -q` → fail. Port. Pass, then the Jev hook tests.

### Task 4: `check` CLI

**Files:** Replace `lib/destructive_guard/check.py`.

**Interfaces (Produces):** `UsageError`, `parse_args(argv) -> dict`, `effective_config(env) -> dict`, `check_call(call, *, env, cwd=None, jev=False) -> dict`, `run(argv, *, env, cwd) -> int`, `main() -> int`.

- [ ] **Step 1:** `GD_IMPL=py uv run pytest plugins/destructive-guard/tests/test_check.py tests/test_corpus.py -q` → fail. Port. Pass (all three corpora now pass through Python `check --json` too).

### Task 5: Latency

**Files:** Create `testkit/bench_gate.py` (script, not a test), `docs/plans/python-port-p8-latency.md` (results table).

- [ ] **Step 1:** `uv run python testkit/bench_gate.py --n 200` runs the same mixed inputs (default packs; Bash allow, Bash ask, script scan, MCP) through `hooks/gate.sh` (JS) and `testkit/_gate_py.sh` (Python); prints p50/p95 per impl. Record the numbers and the machine in the results file. Over budget → stop and report before committing.

### Task 6: Verify, commit

- [ ] **Step 1:** Node suites (735 / 68); `uv run pytest`; `GD_IMPL=py GATE_HOOK_IMPL=py-direct uv run pytest plugins/destructive-guard/tests` (all pass); `uv run ruff check .`.
- [ ] **Step 2:** `docs/plans/python-port.md` §4: mark P8 done (link this file and the latency results).
- [ ] **Step 3:** One commit by file name, `Python port P8: destructive_guard gate, check CLI, hook entry`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
