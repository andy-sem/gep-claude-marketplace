# Python Port P10 (gated-dev `notify.py` + `run-python.sh`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P10 is **one package** (one commit). Tasks 1–3 do not commit; Task 4 commits.
> Written ahead of P3 landing: before starting, re-check names and counts against the committed tests and adjust this file.

**Goal:** the `Notification` hook runs in Python (D4a): `hooks/notify.py` (the P0 D1b stub) hands over to `scripts/gated_dev/notify.py`; `hooks.json` starts it through a new bash launcher `hooks/run-python.sh <script>` (D1a lookup, `-I`); `notify.sh` is deleted. Best-effort: no suitable Python → exit 0 silently. `jq` is no longer needed.

**Architecture:** `run-python.sh` is the general launcher for gated-dev's Python entry points (used by the hook now; skills may call the scripts with `python3` directly). The notify logic mirrors `notify.sh` line by line: off switch, direct mode (two args), hook mode (`TICKET_FLOW_KEY`, stdin JSON `message // title`, default text), OS by `platform.system()` — but the P3 tests stub `uname`, so the module asks `uname -s` through `PATH` like the shell did (keeps the tests unchanged and lets them fake the OS).

**Tech Stack:** bash, Python ≥ 3.14 stdlib (`json`, `subprocess`, `shutil`), pytest.

**Spec:** `hooks/notify.sh`; `tests/test_notify.py` (P3); `docs/plans/python-port.md` D4a; README §Notifications.

**Paths** are relative to `plugins/gated-dev-simple-workflow/` unless they start with `docs/`, `testkit/` or `.claude-plugin/`.

## Global Constraints

- Notifications never fail or block the session: every error path exits 0 with no stdout.
- The P3 notify contract tests stay unchanged except the `jq` row, which becomes "no Python → silent" (and "bad input → default message", without `jq`).
- `osascript` argv identical to `notify.sh` (`-e` lines, `--`, title, message); `notify-send -- <title> <msg>`.
- Node suite for gated-dev drops by the 10 notify tests (`test/notify.test.mjs` deleted); `launch`/`watch-pr` JS tests stay.
- Versions: no bump here (P13 bumps once for the plugin's cutover).

## Review Focus

- `run-python.sh` with no Python, an old Python (exit 3), `GATE_INFRA_PYTHON` broken → exit 0, no output, no stderr noise visible in the session.
- Non-UTF-8 or non-JSON stdin → default message, exit 0.
- Title/message with quotes, newlines, `$()` → passed as argv, never interpolated into AppleScript source.

---

### Task 1: Red tests

**Files:** Modify `tests/test_notify.py`. Create `tests/test_run_python.py`.

- [ ] **Step 1:** Rewrite the `jq` row as `test_default_message_on_bad_input` (no `jq` linked) and add `test_no_python_is_silent` (py impl only: `GATE_INFRA_PYTHON=/nope` and an empty-Python `PATH` → exit 0, no notifier call). `test_run_python.py`: lookup order (`GATE_INFRA_PYTHON`, `python3.14`, `python3`), `-I` (planted `json.py` in cwd ignored), exit 3 from an old Python → exit 0 silent, argv passed through. `test_hooks_json_registers_notification_hook` expects `run-python.sh` + `notify.py` for py.
- [ ] **Step 2:** `GD_IMPL=py uv run pytest plugins/gated-dev-simple-workflow/tests/test_notify.py plugins/gated-dev-simple-workflow/tests/test_run_python.py -q` → fail.

### Task 2: Implement

**Files:** Create `hooks/run-python.sh`. Replace `scripts/gated_dev/notify.py` (placeholder) with the module. Modify `hooks/hooks.json` (`bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/hooks/notify.py"`). Delete `hooks/notify.sh`, `test/notify.test.mjs`.

**Interfaces (Produces):** `gated_dev.notify.main(argv: list[str] | None = None, stdin: BinaryIO | None = None, env: Mapping | None = None) -> int` (always 0; defaults `sys.argv[1:]`, `sys.stdin.buffer`, `os.environ`, since the stub calls `main()` with no arguments).

- [ ] **Step 1:** Implement; Task 1 tests pass with `GD_IMPL=py`.

### Task 3: Flip notify to Python, docs

**Files:** Modify `testkit/impl.py` (`Impl.notify()` for this plugin always uses the py command; `GD_IMPL=js` still applies to `launch`/`watch_pr`), `README.md` (§Notifications: no `jq`; needs Python ≥ 3.14, silent without it), `CLAUDE.md` (gated-dev bullet: `hooks/notify.py` via `run-python.sh`), `tests/PORTING.md` (notify rows unchanged targets; jq row → new test name).

- [ ] **Step 1:** `uv run pytest` (default impl) green.

### Task 4: Verify, commit

- [ ] **Step 1:** `uv run pytest`, `uv run ruff check .`, `node --test 'plugins/gated-dev-simple-workflow/test/*.test.mjs'` (57 = 67 − 10), `claude plugin validate .`.
- [ ] **Step 2:** `docs/plans/python-port.md` §4: mark P10 done (link this file).
- [ ] **Step 3:** One commit by file name, `gated-dev-simple-workflow: Notification hook in Python`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
