# Python Port P3 (gated-dev-simple-workflow tests) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P3 is **one package** (repo rule: one commit per work package). Tasks 1–4 do not commit; Task 5 makes the single commit.

**Goal:** Python tests for all 68 JS tests of `gated-dev-simple-workflow` (`notify`, `launch`, `watch-pr`), green against the current JS (`GD_IMPL=js`), so P10–P12 can port the scripts under them. Closes Phase 1: both `PORTING.md` files fully mapped.

**Architecture:** same three layers as P1/P2. `notify.sh`, `launch.mjs` and `watch-pr.mjs` are CLIs, so most rows become **contract tests** with recording fake binaries on `PATH` (`gh`, `orca`, `osascript`, `notify-send`, `uname`) and real `git` in temp repos. Pure helpers of `launch.mjs` / `watch-pr.mjs` go through the bridge, which learns plugin-qualified module names. The watcher sleeps 60 s between polls through the global `setTimeout`; a node preload (`--import testkit/_fast_timers.mjs`) makes every timer fire at once and records the requested delays, so multi-poll scenarios run in milliseconds without changing `watch-pr.mjs`. The P11 Python twin is a runner that patches `time.sleep` the same way.

**Tech Stack:** Python ≥ 3.14 stdlib, pytest, the P0–P2 `testkit`, node (JS impl + bridge), real `git`.

**Spec:** `docs/plans/python-port.md` (§3 strategy, P3 in §4); behaviour = `plugins/gated-dev-simple-workflow/test/{notify,launch,watch-pr}.test.mjs` + the plugin README. Pattern and test kit: `docs/plans/python-port-p1.md`, `docs/plans/python-port-p2.md`.

## Global Constraints

- Tests only: no change to `scripts/*.mjs`, `hooks/*.sh`, `hooks.json`, skills, agents or any `test/*.test.mjs`. `node --test` suites stay green with unchanged counts (735 / 68).
- Exit criterion: no `todo` row left in `plugins/gated-dev-simple-workflow/tests/PORTING.md` (and none in destructive-guard's, from P2); `uv run pytest` green with `GD_IMPL=js`. Tests that cannot pass with `GD_IMPL=py` yet are expected to fail under it; do not skip or xfail them.
- Contract tests start the scripts only via `impl.notify()`, `impl.launch()`, `impl.watch_pr()` (new `fast=True` variant, Task 1); every subprocess env goes through `testkit.envs.clean_env`; `PATH` is the fake-bin dir plus the dirs of the real tools a test needs (`git`, `bash`), never the developer's full `PATH` (so a real `orca`/`osascript`/`gh` is never reached).
- Bridge-based test modules carry the docstring line `# retarget to gated_dev in P<n>` (watch-pr → P11, launch → P12).
- Public repo hygiene: ticket keys `PROJ-1`…, owner/repo `o/r`, logins `alice`/`bob`; no source-project names.
- Do not touch the untracked `docs/plans/lean-gate-model.md` or the unstaged `.gitignore` change; stage files by name.

## Review Focus

- Fake bins must never fall through to a real tool: a missing stub → `command not found` → test fails loudly (Task 1 `test_fakebin_path_has_no_real_tools`).
- `_fast_timers.mjs` must only shorten delays, not reorder or drop callbacks; it records each delay so "every sleep is 60000 ms" still asserts the real value.
- The `watch-pr` → `check.mjs` import in the JS test becomes a `check` contract call; the cross-plugin dependency must not reappear as a Python import of `destructive_guard`.
- Real `git` in temp repos: set `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, author/committer env, so the developer's git config (hooks, signing) cannot change results.
- Wall time: target < 30 s for the whole P3 suite locally.

---

### Task 1: Test kit — fake bins, git repos, bridge for gated-dev, fast timers

**Files:** Create `testkit/fakebin.py`, `testkit/gitrepo.py`, `testkit/_fast_timers.mjs`. Modify `testkit/_bridge.mjs`, `testkit/bridge.py`, `testkit/impl.py`, `tests/test_testkit_bridge.py`, `tests/test_testkit_impl.py`. Create `tests/test_testkit_fakebin.py`.

**Interfaces (Produces):**
- `testkit.fakebin.FakeBin(tmp: Path)` — `.add(name, *, stdout="", stderr="", status=0, script: list[dict] | None = None, write: dict[str, str] | None = None)` writes an executable Python stub (`#!<require_new_python> -I`) that appends `{"argv": [...], "cwd": ..., "stdin": ...}` to `<tmp>/calls.jsonl`; with `script`, each call consumes the next entry (`{"stdout", "stderr", "status", "write": {path: text}}`, the last one repeating; counter in `<tmp>/<name>.count`). `.link(name)` symlinks the real tool (`shutil.which`) into the dir. `.calls(name=None) -> list[dict]`. `.path` = the dir.
- `testkit.gitrepo.git_env(home: Path) -> dict` (isolated git config env), `init_repo(path, *, origin: Path | None = None, branch="main") -> Path` (one commit, optional bare origin with `origin/HEAD`), `add_worktree(repo, path, branch)`.
- Bridge: module names `"gated-dev:launch"` / `"gated-dev:watch-pr"` resolve to `plugins/gated-dev-simple-workflow/scripts/<name>.mjs`; unqualified names keep meaning `destructive-guard/lib`.
- `testkit/_fast_timers.mjs`: preload that wraps `globalThis.setTimeout` so the delay is `0`; appends each requested delay to `GD_TEST_SLEEP_LOG` (one number per line) when that var is set.
- `Impl.watch_pr(fast: bool = False)` — js: `["node", "--import", <_fast_timers.mjs>, <watch-pr.mjs>]` when `fast`; py: `[python, "-I", <testkit/_fast_sleep.py>, <watch_pr.py>]` (the runner itself lands in P11; until then `fast` with `py` raises `NotImplementedError`).

- [ ] **Step 1: Tests.** `test_fakebin_records_argv_and_stdin`, `test_fakebin_script_sequence_repeats_last`, `test_fakebin_write_side_effect`, `test_fakebin_path_has_no_real_tools` (running `gh` with `PATH=fakebin.path` and no stub → status 127); `test_bridge_gated_dev_module` (`bridge("gated-dev:launch", "slugify", "Fix: Login page!")` equals the JS result); `test_fast_timers_records_delay` (node one-liner `setTimeout(()=>{}, 60000)` under the preload exits < 2 s, log holds `60000`); `test_impl_watch_pr_fast_js`.
- [ ] **Step 2:** `uv run pytest tests -q` → new tests fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `uv run pytest tests -q` → pass; `uv run ruff check .` clean.

### Task 2: notify (10 rows)

**Files:** Create `plugins/gated-dev-simple-workflow/tests/test_notify.py`.

**Interfaces:** Consumes `FakeBin`, `impl.notify()`. Helper `run_notify(*, os="Darwin", env={}, stdin="", with_jq=True, notifiers=("osascript","notify-send"), args=()) -> (status, stderr, calls)` mirrors the JS `run()`: stubs `uname` (prints `os`), the notifiers (recording), links `cat` and (if `with_jq` and found) `jq`; `PATH` = fake dir only.

- [ ] **Step 1:** One test per JS test, same inputs and expected argv. `hooks.json registers notify.sh` → `test_hooks_json_registers_notification_hook`, asserting the `Notification` command runs a file under `hooks/` (name-agnostic: `notify.sh` today, `run-python.sh notify.py` after P10 — assert via `impl`: js → `notify.sh`, py → `run-python.sh`). The jq row keeps its JS meaning (`test_default_message_without_jq_or_bad_input`); P10 rewrites it.
- [ ] **Step 2:** `uv run pytest plugins/gated-dev-simple-workflow/tests/test_notify.py -q` → pass.

### Task 3: watch-pr (20 rows)

**Files:** Create `plugins/gated-dev-simple-workflow/tests/test_watch_pr.py` (contract), `plugins/gated-dev-simple-workflow/tests/test_watch_pr_units.py` (bridge; docstring `# retarget to gated_dev in P11`).

**Interfaces:** Consumes Task 1. Fixtures from the JS test, verbatim: `PR_URL = "https://github.com/o/r/pull/7"`, `T0/T1/T2`, `view(**extra)`, `comment(created_at, **extra)`, `setup(state_extra) -> (dir, state_path, initial)` (`docs/tickets/PROJ-9/state.json`). `fake_gh(fb, polls)` turns the JS poll list into a `FakeBin.add("gh", script=[...])`: each poll is two calls (`gh pr view …` → JSON of the view; `gh api …/comments` → inline JSONL); an `Error` poll → `status 1` on the first call; a poll with `write_state` writes the state file as a side effect. `run_watch(state_path, fb, *, extra_env={}) -> (status, stdout_json, stderr, sleeps)` runs `impl.watch_pr(fast=True) + ["--state", state_path]` with `GD_TEST_SLEEP_LOG`.

- [ ] **Step 1: contract tests** for every `watch(...)`/`main(...)` row: feedback kinds, cutoff (`lastAddressedCommentAt`, file write between polls), bots/marker/empty items, MERGED/CLOSED, MERGED over feedback, 5 failures → `error`, 4+1+4 → no exit (end the scenario with MERGED and assert outcome `merged` after 10 polls), missing/invalid `state.json`, heartbeat fields (read `state.json` after the run: every other field kept, `watch.pid` int, `startedAt` ≤ `heartbeatAt`), heartbeat after a failed poll, every sleep `60000` and `fb.calls()` only `gh`, heartbeat write failure (state dir `chmod 0o555` after setup; stderr matches `heartbeat`; restore mode in teardown), exit code per outcome (`main` row: feedback, merged, closed → 0, error → 1), usage errors (missing `--state`, relative path → exit 2, one JSON line `{"outcome": "usage", ...}`), unparsable PR URL counts as a failed poll. Clock-based JS assertions (`CLOCK`) become ordering assertions on real ISO timestamps.
- [ ] **Step 2: `test_watch_pr_units.py`** — `parsePrUrl` / `normalizePr` row via `bridge("gated-dev:watch-pr", …)`, same inputs and dicts; constants `POLL_MS == 60000`, `MARKER == "<!-- gated-dev -->"`.
- [ ] **Step 3: cross-plugin row** `the watcher command passes destructive-guard with its defaults` → `test_watcher_command_passes_the_gate` uses `testkit.check_cli.check_call` on the exact command line the `ticket` skill documents (read it from `skills/ticket/SKILL.md`, as `test_check.py::test_documented_invocations_pass_the_gate` does), expect `decision == "none"`. No import of destructive-guard code.
- [ ] **Step 4:** `uv run pytest plugins/gated-dev-simple-workflow/tests/test_watch_pr*.py -q --durations=5` → pass.

### Task 4: launch (38 rows)

**Files:** Create `plugins/gated-dev-simple-workflow/tests/test_launch_units.py` (bridge; docstring `# retarget to gated_dev in P12`), `plugins/gated-dev-simple-workflow/tests/test_launch_cli.py` (contract).

**Interfaces:** Consumes Task 1. `repo(config=None, tickets={})` = JS fixture on top of `init_repo` (with a bare origin so `git fetch` works). `run_launch(root, *args, env={}, fb) -> (status, stdout, stderr)` = `impl.launch() + ["--cwd", root, *args]`, `PATH` = fake bins + real `git`/`bash`; host env (`TERM_PROGRAM`, `ORCA_*` handle var, `ITERM_SESSION_ID`) as the JS tests set them.

- [ ] **Step 1: units via bridge** (no `run`/`fs` injection): `buildShellCommand`, `shortSummary`, `sessionName`, hostile title, `slugify`, `detectHost`, `iTermSessionId`, `buildAppleScript`, `buildOrcaArgs`, `orcaWorktreeArgs`, `checkKey`, `parseArgs` — same inputs/outputs, thrown errors via `BridgeError` message regexes. `readConfig`/`readTicket`/`listTicketKeys` take `fs` with a node default, so call them with real temp files (`{root, ...}` args, no `fs`).
- [ ] **Step 2: contract tests** for rows that inject `run`/`fs` (`findRun`, `resolveBase`, `createOrcaWorktree`, `launchTab`, `launchTicket`, `main`): drive `launch.mjs` with fake `orca` (scripted JSON stdout for `worktree create`, `terminal create`, `terminal rename`; a variant that prints garbage or fails), fake `osascript` (records `-e` lines), real git worktrees for `findRun` (`PROJ-1/<slug>` branches; aborted run = its `state.json` stage `aborted`). Assert on `fb.calls()` (argv order and content as the JS asserts on its fake `run`), the human output of `describe()`, exit code, and files copied into the worktree. `--dry-run` rows assert that no fake bin other than `git` was called and no worktree appeared.
- [ ] **Step 3:** If a JS row cannot be expressed through the CLI (an internal decision with no observable effect), bridge it with real temp files instead; if neither works, mark the row `dropped: <reason>` and list it in the commit body for the reviewer. Expectation: none.
- [ ] **Step 4:** `uv run pytest plugins/gated-dev-simple-workflow/tests/test_launch*.py -q --durations=5` → pass.

### Task 5: Map, verify, commit

- [ ] **Step 1:** Fill every row of `plugins/gated-dev-simple-workflow/tests/PORTING.md`. `grep -c '| todo |' plugins/*/tests/PORTING.md` → `0` for both; `uv run pytest tests/test_porting.py -q` → pass.
- [ ] **Step 2:** `node --test 'plugins/destructive-guard/test/*.test.mjs'` (735), `node --test 'plugins/gated-dev-simple-workflow/test/*.test.mjs'` (68), `uv run pytest` (all pass, list skips), `uv run ruff check .`, `claude plugin validate .`. Report `GD_IMPL=py uv run pytest plugins/gated-dev-simple-workflow/tests -q` failure count (information only).
- [ ] **Step 3:** `docs/plans/python-port.md` §4: mark P3 done (link this file) and Phase 1's exit criterion met.
- [ ] **Step 4:** One commit by file name, message `Python port P3: gated-dev-simple-workflow contract tests`, short body, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
