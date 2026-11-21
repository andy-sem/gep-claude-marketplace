# Python Port P9 (destructive-guard cutover) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P9 is **one package** (one commit). Tasks 1–6 do not commit; Task 7 commits. Task 8 (dogfood) runs before the branch is merged, not before the commit.
> Written ahead of P2–P8 landing: before starting, re-check names and counts against the committed tests and adjust this file.

**Goal:** `destructive-guard` runs on Python only. `hooks/gate.sh` starts `lib/gate_main.py` through the D1a interpreter lookup; `GATE_INFRA_NODE` becomes `GATE_INFRA_PYTHON`; the `check` skill, README and the `ticket` skill's gate dry-run use `lib/check.py`; the `impl` default for the plugin flips to `py`; `lib/*.mjs` and `test/*.test.mjs` are deleted; version bump (D6).

**Architecture:** the P8 test wrapper `testkit/_gate_py.sh` becomes the real `hooks/gate.sh` (then the test copy is deleted). The interpreter-lookup tests moved here from P0 (D1b list). The JS impl of this plugin is gone, so `GD_IMPL=js` is rejected for it; the bridge keeps working for gated-dev modules only (until P12).

**Tech Stack:** bash, Python ≥ 3.14, pytest.

**Spec:** `docs/plans/python-port.md` D1a, D1b, D4, D6, Review Focus; current `hooks/gate.sh`; README.

**Paths** are relative to `plugins/destructive-guard/` unless they start with `docs/`, `testkit/`, `tests/`, `.github/`, `.claude-plugin/` or `plugins/gated-dev-simple-workflow/`.

## Global Constraints

- After this package: no `.mjs`/`.js` under `plugins/destructive-guard/`; `node --test 'plugins/gated-dev-simple-workflow/test/*.test.mjs'` still green (count drops by exactly one, Task 5).
- Hook contract tests unchanged except: `impl` default, the `unavailable_reason`/`interpreter_var` now always the Python ones, and rows that named node explicitly.
- `env-guard.sh` is not changed (D4; it never used node).
- Versions: `destructive-guard` minor bump in `plugin.json` and catalog entry, description mentions "needs Python ≥ 3.14"; `metadata.version` bump in `marketplace.json`.
- Public repo hygiene as in `CLAUDE.md`. Stage files by name (deletions with `git rm`).

## Review Focus

- `gate.sh` lookup: `GATE_INFRA_PYTHON` if set (even if broken → ask, no fallback to `PATH`), else `python3.14`, else `python3`; always `-I`; 126/127 and exit 3 → `unparsable: python unavailable`; any other non-zero or no done-file → `gate-config: engine failed`. No version probe process.
- A venv `python3` first on `PATH` that is broken → ask, never allow.
- `GATE_ENABLED=0` still exits before any interpreter starts.
- The `ticket` skill must work with an *older* installed `destructive-guard` (only `check.mjs`) and a newer one (only `check.py`).

---

### Task 1: Interpreter-lookup tests (red)

**Files:** Create `tests/test_gate_sh_lookup.py`.

- [ ] **Step 1:** Tests through `bash hooks/gate.sh` with a fake-bin `PATH` (`testkit.fakebin`): fake `python3` that reports 3.9 (a real old Python via `testkit.pythons.find_old_python()`, skip-with-reason only if none, as `test_entry_stubs.py` does) → ask `python unavailable`; `GATE_INFRA_PYTHON=/nope` → ask; empty `PATH` (no Python) → ask; `python3.14` preferred over an older `python3` on the same `PATH` (record which one ran); broken `python3` (exits 1 without done-file) → `gate-config: engine failed`; planted `json.py` in the project cwd does not change the decision (`-I`). Run → fail (gate.sh still starts node).

### Task 2: `gate.sh`

**Files:** Modify `hooks/gate.sh`. Delete `testkit/_gate_py.sh`; modify `testkit/impl.py` (drop `GATE_HOOK_IMPL`).

- [ ] **Step 1:** Port the `_gate_py.sh` body into `gate.sh`; comments say "python" instead of "node". Run Task 1 tests and `tests/test_gate_hook*.py` with `GD_IMPL=py` → pass.

### Task 3: Flip the impl, delete the JS

**Files:** Modify `testkit/impl.py` (`DEFAULT_IMPL["destructive-guard"] = "py"`; `select_impl` raises for `js` on this plugin), `testkit/bridge.py` + `testkit/_bridge.mjs` (unqualified module names removed; only `gated-dev:` modules), `tests/test_testkit_bridge.py` (self-tests use gated-dev modules), `tests/test_testkit_impl.py`. Delete `lib/{paths,config,gate-engine,gate-scripts,gate-jev,check}.mjs`, `test/*.test.mjs`, `test/fixtures/rules.json` (the Python copy lives in `tests/fixtures/`). Remove `tests/test_rules_loading.py::test_parse_rules_matches_js_shape` (P4; it needs the JS).

- [ ] **Step 1:** `tests/PORTING.md` stays as the record (the JS tests it lists are gone); change `tests/test_porting.py` so a missing JS file for a plugin whose impl is Python-only is accepted, and every row still must have a non-`todo` target.
- [ ] **Step 2:** `uv run pytest plugins/destructive-guard tests -q` → pass with no `GD_IMPL` set.

### Task 4: Skill, README, CLAUDE.md lines for this plugin

**Files:** Modify `skills/check/SKILL.md` (`python3 "${CLAUDE_PLUGIN_ROOT}/lib/check.py" …`, "needs Python ≥ 3.14"; how to point `GATE_INFRA_PYTHON` at a 3.14 if `python3` is older), `README.md` (requirements: Python ≥ 3.14 + install line for Homebrew / `uv python install 3.14` / pyenv / python.org; `GATE_INFRA_PYTHON`; "no node is started" → "no Python is started"; `check` example; test command `uv run pytest plugins/destructive-guard`; file table `lib/destructive_guard/*.py`, `lib/gate_main.py`, `lib/check.py`), `CLAUDE.md` (destructive-guard bullets: file names, "needs Python ≥ 3.14").

- [ ] **Step 1:** `tests/test_readme.py` and `tests/test_check.py::test_documented_invocations_pass_the_gate` pass with the new invocations (the latter reads them from the skill/README).

### Task 5: Cross-plugin references in gated-dev

**Files:** Modify `plugins/gated-dev-simple-workflow/skills/ticket/SKILL.md` (§ gate dry-run: look for `<installPath>/lib/check.py` first and run it with `python3 -I` (or `GATE_INFRA_PYTHON`), else `<installPath>/lib/check.mjs` with `node` for an older installed gate; the fallback is removed in P14), `plugins/gated-dev-simple-workflow/test/watch-pr.test.mjs` (delete the one test that imports `check.mjs`; its Python twin from P3 already covers it), `plugins/gated-dev-simple-workflow/tests/PORTING.md` (that row stays mapped).

- [ ] **Step 1:** `node --test 'plugins/gated-dev-simple-workflow/test/*.test.mjs'` → 67 pass; P3 `test_watcher_command_passes_the_gate` passes on Python `check`.

### Task 6: CI and versions

**Files:** Modify `.github/workflows/test.yml` (drop the destructive-guard node step), `.claude-plugin/plugin.json` of this plugin, `.claude-plugin/marketplace.json`.

- [ ] **Step 1:** `claude plugin validate .`, `jq . .claude-plugin/marketplace.json`.

### Task 7: Verify, commit

- [ ] **Step 1:** `uv run pytest` (all), `uv run ruff check .`, gated-dev node suite (67), `claude plugin validate .`. `find plugins/destructive-guard -name '*.mjs' -o -name '*.js'` → empty.
- [ ] **Step 2:** `docs/plans/python-port.md` §4: mark P9 done (link this file).
- [ ] **Step 3:** One commit by file name, `destructive-guard: run on Python (port cutover)`, body lists the version bump and the new requirement; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.

### Task 8: Dogfood (before merge)

- [ ] **Step 1:** With the user: install the plugin from this branch in a real session (`/plugin marketplace add <local path>`), run a few gated and ungated Bash and MCP calls, `/destructive-guard:check --config`, and one call with only an old `python3` on `PATH` (expect ask `python unavailable`). Same in the demo repo. Record results in the PR description. Push only when the user asks.
