# Python Port P13 (gated-dev cutover) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P13 is **one package** (one commit). Tasks 1–4 do not commit; Task 5 commits. Task 6 (dogfood) runs before the branch is merged.
> Written ahead of P3–P12 landing: before starting, re-check names and counts against the committed tests and adjust this file.

**Goal:** `gated-dev-simple-workflow` runs on Python only. The `ticket` and `launch` skills start `scripts/watch_pr.py` and `scripts/launch.py`; the README lists Python ≥ 3.14 instead of `node` and `jq`; the `impl` default for the plugin flips to `py`; `scripts/*.mjs` and `test/*.test.mjs` are deleted; version bump (D6).

**Architecture:** documentation and wiring only; behaviour is already pinned by the P3 tests passing on Python (P10–P12). Skills invoke scripts with `python3 -I "<path>"` and say how to use `GATE_INFRA_PYTHON` (shared name with the gate, D1a) when `python3` is older than 3.14. The watcher command the `ticket` skill documents must still pass the gate with default packs (P3 `test_watcher_command_passes_the_gate`, now against the new command line).

**Tech Stack:** Markdown, Python ≥ 3.14, pytest.

**Spec:** `docs/plans/python-port.md` D1a, D1c, D6; `skills/ticket/SKILL.md`, `skills/ticket/references/pipeline-spec.md`, `skills/launch/SKILL.md`, README.

**Paths** are relative to `plugins/gated-dev-simple-workflow/` unless they start with `docs/`, `testkit/`, `tests/`, `.github/`, `.claude-plugin/` or `CLAUDE.md`.

## Global Constraints

- After this package: no `.mjs`/`.js` under `plugins/`; no node job steps left for plugin tests in CI (the bridge-only node use goes in P14).
- Agents (`agents/*.md`) unchanged unless they name a script.
- Versions: `gated-dev-simple-workflow` minor bump in `plugin.json` and catalog entry (description: "needs Python ≥ 3.14"); `metadata.version` bump.
- Public repo hygiene as in `CLAUDE.md`. Stage files by name (`git rm` for deletions).

## Review Focus

- Every documented command line in the skills is exercised by a test (watcher via `check`, launcher via `--dry-run` from `test_launch_cli.py` reading the skill text) so docs cannot drift from the code.
- Background watcher: the `ticket` skill still reads the *last stdout line* as JSON; Python prints exactly one line, flushes, and nothing else on stdout.
- `run_in_background` watcher started with `python3 -I`: works when the session's cwd is a worktree (`-I` drops cwd from `sys.path`; the stub adds its own dir).

---

### Task 1: Doc-driven tests (red)

**Files:** Modify `tests/test_watch_pr.py` (`test_watcher_command_passes_the_gate` reads the watcher line from `skills/ticket/SKILL.md`), `tests/test_launch_cli.py` (new `test_documented_invocations_run`: each `launch` command line in `skills/launch/SKILL.md` and the README, with `<plugin>`/`${CLAUDE_PLUGIN_ROOT}` substituted and `--dry-run`, exits 0 on a fixture repo).

- [ ] **Step 1:** Run → fail (docs still say `node … .mjs`).

### Task 2: Skills and README

**Files:** Modify `skills/ticket/SKILL.md` (watcher line: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/watch_pr.py" --state …`; scripts list in §0), `skills/ticket/references/pipeline-spec.md` (`watch_pr.py`), `skills/launch/SKILL.md` (`python3 -I ".../scripts/launch.py"`, "needs Python ≥ 3.14"), `README.md` (requirements: Python ≥ 3.14 with the install line, no `node`, no `jq`; launcher examples; watcher name; test command `uv run pytest plugins/gated-dev-simple-workflow`), `CLAUDE.md` (gated-dev bullets and test line).

- [ ] **Step 1:** Task 1 tests pass.

### Task 3: Flip the impl, delete the JS

**Files:** Modify `testkit/impl.py` (`DEFAULT_IMPL["gated-dev-simple-workflow"] = "py"`; `js` rejected for both plugins now), `tests/test_testkit_impl.py`, `tests/test_porting.py` if needed. Delete `scripts/launch.mjs`, `scripts/watch-pr.mjs`, `test/launch.test.mjs`, `test/watch-pr.test.mjs`. Bridge-dependent tests: none should remain after P11/P12 retargets; `grep -rn 'bridge(' plugins` → empty.

- [ ] **Step 1:** `uv run pytest` green with no `GD_IMPL` set.

### Task 4: CI and versions

**Files:** Modify `.github/workflows/test.yml` (drop the gated-dev node step; the node job keeps only the manifest validation, or merge it into the Python job — the node setup itself goes in P14), `.claude-plugin/plugin.json` (this plugin), `.claude-plugin/marketplace.json`.

- [ ] **Step 1:** `claude plugin validate .`, `jq . .claude-plugin/marketplace.json`.

### Task 5: Verify, commit

- [ ] **Step 1:** `uv run pytest`, `uv run ruff check .`, `claude plugin validate .`; `find plugins -name '*.mjs' -o -name '*.js'` → empty.
- [ ] **Step 2:** `docs/plans/python-port.md` §4: mark P13 done (link this file).
- [ ] **Step 3:** One commit by file name, `gated-dev-simple-workflow: run on Python (port cutover)`, body lists the version bump and requirement change; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.

### Task 6: Dogfood (before merge)

- [ ] **Step 1:** With the user: `/ticket` on a demo ticket through plan approval and PR, watcher wakes on a review comment and on merge; `launch --dry-run --all` and one real launch in Orca or iTerm2; a notification from a launcher-started session. Record results in the PR description. Push only when the user asks.
