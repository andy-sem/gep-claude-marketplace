# Python Port P14 (cleanup: no JavaScript left) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P14 is **one package** (one commit). Tasks 1–4 do not commit; Task 5 commits.
> Written ahead of P1–P13 landing: before starting, re-check what is left and adjust this file.

**Goal:** the repo contains no JavaScript and no `node` invocation: the bridge, the `js` impl, the node CI setup, the `check.mjs` fallback in the `ticket` skill and every `node` mention in this repo's own docs are gone; a test keeps it that way. `CLAUDE.md`, catalog descriptions and `metadata.version` are final; the port plan is closed.

**Architecture:** removal plus one guard test. Rule content that *recognises* JS in user commands (`node x.mjs`, `npx`, `pnpm run` in packs, `gate_scripts` JS/TS file kinds, README §Scripts examples) is not project JS and stays (Global Constraints of `docs/plans/python-port.md`).

**Tech Stack:** Python ≥ 3.14, pytest, GitHub Actions.

**Spec:** `docs/plans/python-port.md` Goal, Global Constraints, P14 in §4.

## Global Constraints

- One commit; all suites green; `claude plugin validate .` clean.
- The guard test allows `node`/`.mjs` only in: `plugins/destructive-guard/packs/*.json`, `plugins/destructive-guard/lib/destructive_guard/gate_scripts.py` and `gate_engine.py` (recognition logic), test case corpora and fixtures under `plugins/*/tests/`, the README sections that describe what the gate recognises, and `docs/plans/` (history).
- Public repo hygiene as in `CLAUDE.md`. Stage files by name.

## Review Focus

- The guard test must fail on a real regression (a `node` line in a skill, a `.mjs` file anywhere, `setup-node` in CI) and not on rule content; include one negative fixture per allowed category to prove the allowlist is narrow.
- The `ticket` skill's gate dry-run without the `check.mjs` fallback: an installed `destructive-guard` older than the P9 version now means "no `GATE_CHECK`" (planner writes `unknown`), documented in one line.

---

### Task 1: Guard test (red)

**Files:** Create `tests/test_no_js.py`.

- [ ] **Step 1:** Assertions: no `*.js`/`*.mjs`/`*.cjs` file tracked by git (`git ls-files`); no `node ` / `npx ` invocation in `plugins/*/hooks/*`, `plugins/*/skills/**/*.md`, `plugins/*/agents/*.md`, `.github/workflows/*.yml`, `CLAUDE.md`, plugin READMEs outside the allowed sections (mark them with `<!-- recognises-js -->` … `<!-- /recognises-js -->` comments); no `setup-node` in CI; no `GATE_INFRA_NODE` anywhere outside `docs/plans/`. Run → fail (bridge, CI, skill fallback still there).

### Task 2: Remove test-kit JS

**Files:** Delete `testkit/_bridge.mjs`, `testkit/bridge.py`, `testkit/_fast_timers.mjs`, `tests/test_testkit_bridge.py`. Modify `testkit/impl.py` (drop the `js` branch, `Impl.name` only `py`; `GD_IMPL` accepted only as `py` or unset — or drop `GD_IMPL` entirely and simplify `Impl`; pick the smaller diff), `tests/test_testkit_impl.py`, `tests/test_testkit_contract.py`, `pyproject.toml` comments if they mention node.

- [ ] **Step 1:** `uv run pytest` green.

### Task 3: CI, skill fallback, docs

**Files:** Modify `.github/workflows/test.yml` (one Python job: manifests via `python -m json.tool` or `jq`, `uv run ruff check .`, `uv run pytest` on `3.14` and `3.x`; no `setup-node`), `plugins/gated-dev-simple-workflow/skills/ticket/SKILL.md` (drop the `check.mjs` fallback), both plugin READMEs (remaining `node` mentions outside the recognition sections; add the markers), `CLAUDE.md` (test commands: only `uv sync`, `uv run pytest`, `uv run ruff check .`, `claude plugin validate .`, `jq`; "needs Node.js" → "needs Python ≥ 3.14"; drop `GD_IMPL` note; module names).

- [ ] **Step 1:** Task 1 test passes.

### Task 4: Versions and plan close-out

**Files:** Modify `.claude-plugin/marketplace.json` (`metadata.version` bump; catalog descriptions final), plugin `plugin.json` files only if their description still mentions node; `docs/plans/python-port.md` (mark P14 done, add a short "Outcome" section: final test counts, latency numbers from P8, known differences if any, and that `PORTING.md` files are kept as the record); `CLAUDE.md` "Work in progress" section updated.

- [ ] **Step 1:** `claude plugin validate .`, `jq . .claude-plugin/marketplace.json`.

### Task 5: Verify, commit

- [ ] **Step 1:** `uv run pytest`, `uv run ruff check .`, `claude plugin validate .`; `git ls-files | grep -E '\.(m|c)?js$'` → empty.
- [ ] **Step 2:** One commit by file name, `Python port P14: remove the last JavaScript`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push; ask the user about pushing and opening the PR (superpowers:finishing-a-development-branch).
