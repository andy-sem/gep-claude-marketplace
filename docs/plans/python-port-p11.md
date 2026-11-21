# Python Port P11 (gated-dev `watch_pr.py`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P11 is **one package** (one commit). Tasks 1–3 do not commit; Task 4 commits.
> Written ahead of P3 landing: before starting, re-check names and counts against the committed tests and adjust this file.

**Goal:** `gated_dev.watch_pr`: the PR watcher in Python (`gh pr view` + inline comments, feedback after the cutoff, MERGED/CLOSED, 5 failures in a row, heartbeat in `state.json`, one JSON line, exit codes). The P3 contract tests pass with `GD_IMPL=py`; the P3 bridge tests are retargeted. The skill still starts the JS watcher until P13.

**Architecture:** one module mirroring `watch-pr.mjs` with injectable `run`, `now`, `sleep`, `log`, `pid` (keyword arguments, JS defaults). `scripts/watch_pr.py` (P0 stub) calls `main()`. The P3 `fast=True` contract runner for Python, `testkit/_fast_sleep.py`, is added here: it patches `time.sleep` to record the delay in `GD_TEST_SLEEP_LOG` and return at once, then runs the target stub with `runpy.run_path` (so the stub's version check and `-I` path logic run unchanged).

**Tech Stack:** Python ≥ 3.14 stdlib (`subprocess`, `json`, `datetime`, `os.replace`, `re`), pytest.

**Spec:** `scripts/watch-pr.mjs`; `tests/test_watch_pr.py`, `tests/test_watch_pr_units.py` (P3); `skills/ticket/references/pipeline-spec.md` (`watch` field, outcomes).

**Paths** are relative to `plugins/gated-dev-simple-workflow/` unless they start with `docs/`, `testkit/` or `pyproject.toml`.

## Global Constraints

- Conventions of `docs/plans/python-port-p4.md` §Conventions apply (snake_case, JS-shaped data: `state.json` keys `watch.pid`, `watch.startedAt`, `watch.heartbeatAt`, `lastAddressedCommentAt`; output JSON keys `outcome`, `prUrl`, `newestAt`, `message`, `at`).
- `pyproject.toml` `pythonpath` gains `plugins/gated-dev-simple-workflow/scripts`.
- Timestamps: ISO 8601 UTC with milliseconds and `Z` (`2026-10-22T12:00:00.000Z`), as JS `toISOString()`.
- Heartbeat write is atomic (temp file in the same dir + `os.replace`), state written with `indent=2` and a trailing newline.
- `gh` runs with the state file's directory as cwd; stdout limit at least 64 MiB.
- No change to `watch-pr.mjs` or its JS tests; node suite unchanged.

## Review Focus

- Cutoff parsing: an unparsable `lastAddressedCommentAt` falls back to the PR creation time as `Date.parse` → `NaN` does in JS; comparison on parsed instants, not strings.
- Bots (`[bot]` suffix / `app/` logins as JS), marker `<!-- gated-dev -->`, empty bodies, a review counts with a body or `CHANGES_REQUESTED`.
- Failure counter resets after a success; heartbeat written even after a failed poll; heartbeat failure only logged.

---

### Task 1: Retarget units, fast runner (red)

**Files:** Modify `tests/test_watch_pr_units.py` (remove the marker, import `gated_dev.watch_pr`), `testkit/impl.py` (`watch_pr(fast=True)` for py). Create `testkit/_fast_sleep.py`, a test in `tests/test_testkit_impl.py` for it (repo-root `tests/`).

- [ ] **Step 1:** `GD_IMPL=py uv run pytest plugins/gated-dev-simple-workflow/tests/test_watch_pr*.py -q` → fail.

### Task 2: Module

**Files:** Replace `scripts/gated_dev/watch_pr.py`.

**Interfaces (Produces):** `POLL_MS = 60_000`, `MAX_GH_FAILURES = 5`, `MARKER`, `EXIT = {"feedback": 0, "merged": 0, "closed": 0, "error": 1, "usage": 2}`, `default_run(cmd, args, *, cwd=None) -> str`, `parse_pr_url(url) -> dict | None`, `normalize_pr(view, inline=()) -> dict`, `fetch_pr(url, run=default_run, cwd=None) -> dict`, `newest_feedback_at(items, cutoff) -> str | None`, `new_feedback_at(pr, last_addressed) -> str | None`, `watch(*, state_path, run=..., now=..., sleep=..., log=..., pid=...) -> dict`, `main(argv=None, **deps) -> int`.

- [ ] **Step 1:** Port; add direct unit tests for `watch` with Python fakes for the two scenarios that are slow or awkward as contract tests (heartbeat failure, clock order with a fixed `now` sequence, matching the JS `CLOCK` assertions exactly).
- [ ] **Step 2:** Task 1 tests and the new ones pass with `GD_IMPL=py`.

### Task 3: Both impls green

- [ ] **Step 1:** `uv run pytest plugins/gated-dev-simple-workflow -q` and the same with `GD_IMPL=py` (watch-pr files) → pass. `launch` tests still need JS — expected.

### Task 4: Verify, commit

- [ ] **Step 1:** `uv run pytest`, `uv run ruff check .`, gated-dev node suite (unchanged count).
- [ ] **Step 2:** `docs/plans/python-port.md` §4: mark P11 done (link this file).
- [ ] **Step 3:** One commit by file name, `Python port P11: gated_dev watch_pr`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
