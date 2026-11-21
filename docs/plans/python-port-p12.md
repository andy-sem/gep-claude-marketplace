# Python Port P12 (gated-dev `launch.py`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P12 is **one package** (one commit). Tasks 1–4 do not commit; Task 5 commits.
> Written ahead of P3 landing: before starting, re-check names and counts against the committed tests and adjust this file.

**Goal:** `gated_dev.launch`: the ticket launcher in Python (keys or `--all`, `--dry-run`, `--remote-control`, `--cwd`; Orca worktrees and terminals, iTerm2 tabs via AppleScript, resume of existing runs, base branch resolution, config and ticket reading). The P3 contract tests pass with `GD_IMPL=py`; the P3 bridge tests are retargeted.

**Architecture:** one module mirroring `launch.mjs` section by section (quoting and naming helpers → host detection → AppleScript/Orca argv builders → config/ticket/run lookup → worktree creation → tab launch → `launch_ticket` → CLI). Process calls go through an injectable `run(file, argv) -> CompletedRun` (stdout, stderr), filesystem through `pathlib` (no `fs` injection: the P3 tests use real temp repos). `scripts/launch.py` (P0 stub) calls `main()`.

**Tech Stack:** Python ≥ 3.14 stdlib (`subprocess`, `json`, `re`, `pathlib`, `shutil`, `shlex` only for `quote`-style output checks if it matches JS `shellQuote` exactly — otherwise a port of `shellQuote`), pytest.

**Spec:** `scripts/launch.mjs`; `tests/test_launch_units.py`, `tests/test_launch_cli.py` (P3); `skills/launch/SKILL.md`; `skills/ticket/references/config.md`; README §Launcher.

**Paths** are relative to `plugins/gated-dev-simple-workflow/` unless they start with `docs/` or `testkit/`.

## Global Constraints

- Conventions of `docs/plans/python-port-p4.md` §Conventions (snake_case, JS-shaped data and error messages).
- Shell and AppleScript strings are built only through the ported `shell_quote` / `apple_script_string`; a hostile title or key never reaches a shell or AppleScript unquoted (P3 hostile-title row).
- Human output (`describe()` lines) and usage text byte-identical to JS.
- No change to `launch.mjs` or its JS tests; node suite unchanged.

## Review Focus

- `shell_quote` parity with JS for `'`, newlines, empty string; `slugify` and `short_summary` on non-ASCII titles (JS `toLowerCase`/regex behaviour vs Python `str.lower`/`re`): pin with the P3 bridge cases plus a few non-ASCII cases generated from JS before retargeting.
- `find_run`: several `<KEY>/*` worktrees → error; aborted runs ignored; porcelain parsing tolerant of `detached` entries.
- Orca JSON shapes (`result.terminal.handle`, `result.handle`, `handle`) and a failing `orca worktree create` never falls back to git.

---

### Task 1: Pin non-ASCII helper cases, retarget units (red)

**Files:** Create `tests/fixtures/launch_helpers.json` (generated once from JS via the bridge: `slugify`, `shortSummary`, `sessionName`, `shellQuote`, `appleScriptString` over ~30 inputs incl. non-ASCII, quotes, newlines). Modify `tests/test_launch_units.py` (import `gated_dev.launch`, remove the marker; add the fixture table test).

- [ ] **Step 1:** Generate and commit the fixture while the JS still exists; `GD_IMPL=py uv run pytest plugins/gated-dev-simple-workflow/tests/test_launch*.py -q` → fail.

### Task 2: Pure helpers

**Files:** Replace `scripts/gated_dev/launch.py` (placeholder).

**Interfaces (Produces):** `shell_quote`, `apple_script_string`, `is_safe_key`, `short_summary`, `session_name(*, key, args=(), summary=None)`, `slugify`, `detect_host(env)`, `iterm_session_id(env)`, `build_shell_command(...)`, `build_apple_script(...)`, `build_orca_args(...)`, `orca_worktree_args(*, root, key, title, base)`, `parse_args(argv)`.

- [ ] **Step 1:** Port; unit tests pass.

### Task 3: Repo, config, tickets, runs

**Interfaces (Produces):** `find_root(*, cwd, run)`, `read_config(*, root)`, `check_key(key, config)`, `read_ticket(*, root, key, config)`, `list_ticket_keys(*, root, config)`, `find_run(*, root, key, config, run)`, `resolve_base(*, root, ticket, config, run)`, `orca_has_repo(*, root, run)`.

- [ ] **Step 1:** Port; the matching unit and CLI tests pass.

### Task 4: Worktrees, tabs, `launch_ticket`, CLI

**Interfaces (Produces):** `create_orca_worktree(...)`, `launch_tab(...)`, `launch_ticket(*, root, key, config, remote_control, dry_run, env, run, log) -> dict`, `main(argv=None, *, env=None, run=None, out=None, err=None) -> int`.

- [ ] **Step 1:** Port; `GD_IMPL=py uv run pytest plugins/gated-dev-simple-workflow -q` → all pass (launch, watch-pr, notify).

### Task 5: Verify, commit

- [ ] **Step 1:** `uv run pytest`, `GD_IMPL=py uv run pytest plugins/gated-dev-simple-workflow -q`, `uv run ruff check .`, gated-dev node suite (unchanged count).
- [ ] **Step 2:** `docs/plans/python-port.md` §4: mark P12 done (link this file).
- [ ] **Step 3:** One commit by file name, `Python port P12: gated_dev launch`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
