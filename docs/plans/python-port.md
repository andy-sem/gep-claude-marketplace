# Python Port Implementation Plan (general)

> **For agentic workers:** this is the phase-level plan. Before a work
> package starts, write its step-level plan (superpowers:writing-plans,
> TDD steps) and execute it with superpowers:subagent-driven-development
> (chosen by the user: a fresh implementer subagent and a fresh reviewer per
> package). Check off packages in §4 as they land.

**Goal:** both plugins run on Python only, and **the project gives up
JavaScript entirely**: no `.mjs`/`.js` files, no `node` in hooks, skills,
READMEs, CI or `CLAUDE.md` at the end. Behaviour stays the same; the READMEs
stay the reference.

**Architecture:** tests first, then code. The Python test suite is written
and made green *against the current JS implementation* (black-box contract
tests + a shared case corpus), then each module is rewritten in Python under
those same tests, and the JS is deleted plugin by plugin.

**Tech Stack:** Python ≥ 3.14 stdlib (runtime), pytest + ruff (dev only, uv), bash shims
for fail-closed hooks.

**Spec:** this document + the current behaviour pinned by the JS tests and
the plugin READMEs.

## Global Constraints

- Runtime: Python ≥ 3.14, standard library only; no pip install for users (they install the interpreter, see D1).
- No JavaScript left in the repo after P14; a test asserts there is no
  `*.js`/`*.mjs` file and no `node` invocation in hooks, skills or CI.
- Exception: the gate still *recognises* `node x.mjs`, `npx`, `pnpm run` in
  user commands; that is rule content, not project JS.
- Public repo hygiene from `CLAUDE.md` applies to new tests (fictional tools,
  no named MCP servers, no source-project names).
- One commit per work package; every commit keeps all test suites green.

## Review Focus

- Hook stdin with non-ASCII / invalid UTF-8 → same decision as JS today, never a crash-allow.
- Only an older `python3` on `PATH` (macOS 3.9), or a broken venv `python3` first on `PATH` → `gate.sh` asks, never allows.
- Pack or user regex valid in JS but different in Python `re` → corpus catches it; invalid one → `gate-config:` ask.
- Gate latency on every Bash/MCP call → measured in P8, no slower than JS by more than ~50 ms p95.
- Hook output bytes (JSON shape, trailing newline) → one exact-bytes contract test per hook.

## 1. Scope

| Plugin | JS today | Lines (code / tests) |
| --- | --- | --- |
| `destructive-guard` | `lib/{paths,config,gate-engine,gate-scripts,gate-jev,check}.mjs` | ~3.4k / ~4.3k |
| `gated-dev-simple-workflow` | `scripts/{launch,watch-pr}.mjs` | ~1.1k / ~1.1k |

Also touched: `hooks/gate.sh` (starts node), `skills/*/SKILL.md`, both
READMEs, `ticket` skill (calls `check.mjs`, `watch-pr.mjs`),
`.github/workflows/test.yml`, `CLAUDE.md`.

Not ported (no JS in them): rule packs and Jev prompts (`packs/*.json`,
`jev/*.json`), agents, `env-guard.sh` (see decision D4). `notify.sh` has
no JS but moves to Python too (D4a).

## 2. Decisions (confirmed by the user, 2026-11-20)

- **D1 Runtime:** Python ≥ 3.14 (decided by the user, 2026-11-20, after
  weighing 3.11: accepted trade-off is that most machines must install
  3.14 first, since Claude Code's native install brings neither Node nor
  Python and system `python3` is usually 3.9–3.13). **Stdlib only** at
  runtime, like today's zero-npm-deps rule. Jev uses `urllib.request`.
  Modern syntax is fine (`match`, PEP 695 generics, `type` aliases).
  Users install 3.14 themselves (Homebrew, `uv python install 3.14`,
  pyenv, python.org); the README says so.
- **D1a Interpreter lookup:** the hook shims use `GATE_INFRA_PYTHON` if set,
  else the first of `python3.14`, `python3` on `PATH` (so a 3.14 installed
  next to an older default `python3` is found), and always run it
  with `-I` (isolated mode: ignores `PYTHONPATH`, `PYTHONHOME`-style env
  vars, user site-packages and the current directory, so a `json.py` planted
  in the user's project cannot hijack the gate).
- **D1b Version check:** a too-old Python cannot even *parse* 3.14 code (a
  `SyntaxError` happens before any `if sys.version_info` runs), so every
  entry point is a tiny stub written in syntax any Python ≥ 3.7 can parse:
  `lib/gate_main.py`, `lib/check.py`, `scripts/launch.py`,
  `scripts/watch_pr.py`, `hooks/notify.py`. The stub checks
  `sys.version_info >= (3, 14)`, and only then imports the real package.
  Too old → exit code `3` and one stderr line
  `needs Python >= 3.14 (found X.Y at <sys.executable>); set GATE_INFRA_PYTHON`.
  `gate.sh` maps "interpreter not found" (126/127) and exit `3` to
  ask `python unavailable`; any other failure stays `gate-config: engine
  failed`. One process per call, no extra version probe. Tests (P0):
  fake `python3` on `PATH` that reports 3.9 → ask; `GATE_INFRA_PYTHON`
  pointing at a missing file → ask; no Python on `PATH` → ask; stub run
  under 3.14 → imports the package; `python3.14` preferred over an older
  `python3` on the same `PATH`. A unit test parses each stub with
  `ast.parse(src, feature_version=(3, 7))` so nobody "modernises" them
  (walrus, `match` would fail it).
- **D1d Floor enforced in code:** `pyproject.toml` sets
  `requires-python = ">=3.14"` and `ruff` (dev-only) uses
  `target-version = "py314"`; CI runs the suite on 3.14 **and** the latest
  Python.
- **D1c System Python vs venv:** *users* run the plugins on a
  system-installed Python ≥ 3.14 (any installer), **no venv**. The runtime is
  stdlib-only, so a venv adds nothing, and plugins have no install step to
  create one; building it lazily inside a hook would add seconds to the
  first gated call and a new failure mode. `-I` already gives the isolation
  a venv would. *Developers* use a venv for the dev tools only:
  `pyproject.toml` (no runtime deps, dev group `pytest`),
  `.python-version` = `3.14` (develop on the floor), `uv sync` → `.venv/` (git-ignored), tests via
  `uv run pytest`. CI does the same with `astral-sh/setup-uv`. Tests always
  start hooks and CLIs through the D1a lookup, never with the venv's
  `sys.executable` directly, so they exercise what users get.
- **D2 Tests:** `pytest` as a dev-only dependency (parametrised case tables
  are the bulk of the gate tests). Run with `uv run pytest plugins/*/tests`.
- **D3 Layout:** `lib/*.mjs` → `lib/destructive_guard/*.py` (package),
  `scripts/*.mjs` → `scripts/*.py`; entry points stay runnable as files
  (`python3 lib/check.py ...`), so skills keep a one-line invocation.
- **D4 Shell wrappers stay:** `gate.sh` and `env-guard.sh` remain thin bash
  shims because the fail-closed guarantee ("interpreter missing → ask") must
  live outside the interpreter. `gate.sh` starts the D1a interpreter; the
  `node unavailable` reason becomes `python unavailable`;
  `GATE_INFRA_NODE` is renamed `GATE_INFRA_PYTHON` (no alias: JS is gone).
- **D4a `notify.sh` → Python:** the logic moves to `hooks/notify.py`
  (D1b stub + module). `hooks.json` starts it through a small bash launcher
  `hooks/run-python.sh <script>` that does the D1a lookup and runs it with
  `-I`. Unlike the gate, notifications are best-effort: no suitable Python
  (not found or exit `3`) → exit 0 silently, never blocking the session.
  Same behaviour as today otherwise: only for launcher-started sessions
  (`TICKET_FLOW_KEY`), macOS `osascript`, Linux `notify-send`, silent
  elsewhere, `GATED_DEV_NOTIFY=0` disables; `jq` is no longer needed
  (Python reads the hook JSON).
- **D5 Regex dialect:** pack and user rule regexes are evaluated by Python
  `re` after the port. A test compiles every pack regex; a user
  `GATE_RULES_FILE` regex that fails to compile asks with `gate-config:`
  (same as any config error today).
- **D6 Versioning:** each plugin gets a minor bump on cutover (behaviour is
  unchanged; the runtime requirement changes, noted in the README).

## 3. Strategy: how Python tests can run against JS

Python cannot import `.mjs`. Three kinds of tests, each with its own bridge:

1. **Contract tests (black box).** Drive the real entry points as
   subprocesses: hook stdin JSON → stdout/exit (`gate.sh`, `env-guard.sh`,
   `notify.sh`), `check` CLI (`--json`, `--config`, `--mcp`), launcher
   `--dry-run`, watcher with a fake `gh` on `PATH`. A fixture
   `impl` (`GD_IMPL=js|py`, default `js` until cutover) picks the command
   line. These tests don't change at cutover; only the default flips.
2. **Case corpus.** The table-driven cases (command → decision + rule id,
   MCP call → decision, script → findings) move out of the JS tests into
   `tests/cases/*.json`. Pytest runs them through the contract layer. This is
   most of the gate's coverage and is the regression net for the port.
3. **Unit tests of internals** (tokenizer output, config parsing, redaction,
   Jev response parsing, PR normalisation). Two options per function:
   - *pure, JSON-in/JSON-out:* call JS through a tiny temporary
     `tests/_bridge.mjs` (`node _bridge.mjs <module> <fn> <json-args>` →
     JSON result) so the test is green on JS first, then retarget to the
     Python import;
   - *needs mocks/callbacks* (Jev HTTP, `gh`, timers): written in Python as
     red tests immediately before the module is ported (plain TDD).

   The bridge and the `js` impl are deleted in the cleanup package.

Parity check: `tests/PORTING.md` lists every JS `test(...)` name with the
Python test that covers it (or "dropped: reason"). A package is done only
when its JS tests are all mapped.

## 4. Phases and work packages

One commit per package (repo rule). Each package keeps
`node --test` **and** `pytest` green until the JS is removed.

### Phase 0: groundwork

- **P0** (done, see `docs/plans/python-port-p0.md`; the `gate.sh` / `run-python.sh` interpreter-lookup tests moved to P9 / P10) `pyproject.toml`, `.python-version`, `.venv/` in `.gitignore`,
  pytest config, `impl` fixture, `_bridge.mjs`, `tests/PORTING.md`
  skeleton, CI job with `astral-sh/setup-uv` (Python 3.14 and latest) next to the
  node job. The D1b version-check stubs (entry stubs that only check the
  version and exit, real imports come later) with their tests.
  `CLAUDE.md` gets the new test command.

### Phase 1: Python tests, green against JS

- **P1** (done, see `docs/plans/python-port-p1.md`) `destructive-guard` contract + corpus: `gate-hook`, `env-guard`,
  `check`, `destructive`, `gate-rules`, `packs`, `readme`, `jev-prompt`
  (prompt files and "no named MCP servers" rule). The 344 rule cases live in
  `tests/cases/*.json` and run through `check --json` (verified equal to
  `classify`); the two `Read` cases go through `gate.sh`, since `--mcp` only
  takes `mcp__` tools. The JS handling of invalid UTF-8 on hook stdin (bad bytes
  replaced, decision as usual) and the exact ask bytes are pinned. CI's Python
  job uses `actions/setup-python` (`3.14`, `3.x`). With `GD_IMPL=py` the
  `check` tests fail (placeholder `check.py`); most hook tests still pass
  because `gate.sh` keeps calling node until P9.
- **P2** (plan: `docs/plans/python-port-p2.md`) **done**. `destructive-guard` units: `config`, `gate-engine`,
  `gate-scripts`, `gate-jev` (120 JS tests, no `todo` row left in `PORTING.md`). The test kit gained nested
  bridge calls (`call`), batching (`bridge_many`), `js_regexp`, and Jev mock headers, `retry_after`, raw
  bodies and answer sequences. The 189 engine classify cases are a third corpus, `cases/gate_engine.json`.
- **P3** (plan: `docs/plans/python-port-p3.md`) **done**. `gated-dev-simple-workflow`: `notify`, `launch` (fake
  `orca`/`osascript` on a private `PATH`, real git repos), `watch-pr` (fake `gh`; the test's dependency on
  `check.mjs` goes through the `check` contract instead of an import). All 68 JS tests mapped, no `todo` row
  left in either `PORTING.md`. The test kit gained `FakeBin`, `gitrepo`, bridge module names `gated-dev:<script>`,
  the `_fast_timers.mjs` preload and `Impl.watch_pr(fast=True)`.
- Jev (`gate-jev`) tests that need a mock HTTP server stay as contract tests
  through `gate.sh` with a local server (as `gate-hook.test.mjs` does now);
  pure helpers via the bridge.

Exit criterion (met after P3): `PORTING.md` fully mapped, pytest green with `GD_IMPL=js`.

### Phase 2: port `destructive-guard` (bottom-up)

The Python package is built next to the JS; hooks keep calling JS until P9.

- **P4** (plan: `docs/plans/python-port-p4.md`) **done**. `paths`, `config` (env → effective config, pack composition).
  Rule loading (`loadRules`, `composeRules`, `loadPacks`, `parseRules`) moved out of `gate-engine.mjs` into its own
  module `rules.py` (`config` needs it, the parser of P5 does not); `gate_engine.py` re-exports it in P5. The package
  `plugins/destructive-guard/lib/destructive_guard/` is on pytest's `pythonpath` and ruff's `src`.
- **P5** (plan: `docs/plans/python-port-p5.md`) **done**, one commit (no split). `gate_engine`: shell parser
  (`sudo`/`xargs`/`bash -c`/`npx` unwrapping), rule evaluation, `classify`. All 537 corpus cases give the JS rule id
  through the Python `classify` (`test_*_case_py`); the tokenizer and normalisation are pinned by two JS-generated
  fixtures (516 + 1002 rows); `test_gate_engine.py` has no bridge left.
- **P6** (plan: `docs/plans/python-port-p6.md`) **done**. `gate_scripts`: project root, run targets (shell, node, python,
  package scripts, workflows, `terraform test`), source/import following within limits, scan; `test_gate_scripts.py` has
  no bridge left.
- **P7** (plan: `docs/plans/python-port-p7.md`) **done**. `gate_jev`: configuration, prompts, redaction, request
  (`urllib.request`, injectable opener, one time budget, `retry-after`), decision and audit log;
  `test_jev_units.py` and `test_jev_prompt.py` have no bridge left, `test_jev_request_py.py` mirrors every
  `test_jev_http.py` row in-process.
- **P8** (plan: `docs/plans/python-port-p8.md`) **done**. `gate()` (rules + script scan + Jev), the hook entry
  `gate_main.main` (done-file protocol, `GATE_LOG`) and the `check` CLI. `GATE_HOOK_IMPL=py-direct` runs the hook
  contract tests on Python through the test-only `testkit/_gate_py.sh` until P9. Latency: Python p95 is 43 ms
  below JS (`docs/plans/python-port-p8-latency.md`).
- **P9** (plan: `docs/plans/python-port-p9.md`) **done** (dogfood before merge still open). Cutover: `gate.sh` → D1a interpreter lookup, `GATE_INFRA_PYTHON`, skill and
  README updates, flip `impl` default to `py` for this plugin, delete
  `lib/*.mjs` and `test/*.test.mjs`, version bump. Dogfood in a real
  session and in the demo repo before merging.

### Phase 3: port `gated-dev-simple-workflow`

- **P10** (plan: `docs/plans/python-port-p10.md`) **done**. `notify.py` + `run-python.sh` (D4a); `hooks.json` switches to it,
  `notify.sh` is deleted. The P3 notify contract tests stay unchanged
  except the `jq`-missing case, which becomes "no Python → silent".
- **P11** (plan: `docs/plans/python-port-p11.md`) **done**. `watch_pr.py` (PR polling, heartbeat, follow-up rounds, marker).
- **P12** (plan: `docs/plans/python-port-p12.md`) **done**. `launch.py` (worktrees, Orca/iTerm2, `--dry-run`, `--all`).
- **P13** (plan: `docs/plans/python-port-p13.md`) Cutover: `ticket`/`launch` skills, `SKILL.md` gate dry-run step
  (`lib/check.py`), README requirements (Python ≥ 3.14 instead of `node`
  and `jq`), delete JS + node tests, version bump.

### Phase 4: cleanup

- **P14** (plan: `docs/plans/python-port-p14.md`) Remove `_bridge.mjs`, the `js` impl, the node CI job, and the
  `node` mentions in this repo's docs; add the "no JS in the repo" test; update
  `CLAUDE.md` (test commands, "needs Node.js" → "needs Python ≥ 3.14"),
  catalog descriptions and `metadata.version`; close this plan.

## 5. Risks

| Risk | Mitigation |
| --- | --- |
| Behaviour drift in the hand-written shell parser | Keep the parser hand-written (do **not** switch to `shlex`); full case corpus through both impls before cutover |
| JS vs Python regex differences in packs (`\d`/`\s` Unicode, lookbehind, flags) | Compile-all-packs test; corpus run on both impls; `re.ASCII` where JS semantics need it |
| Hook latency on every Bash/MCP call | Measure p50/p95 of `gate.sh` on both impls in P8; avoid heavy imports, lazy-load Jev |
| Python 3.14 not installed on most machines (system `python3` is 3.9–3.13) | D1a lookup + version check; `gate.sh` asks (`python unavailable`), never allows; README install line; `check` skill prints the fix |
| JSON output differences (key order, escaping, trailing newline) | Contract tests compare parsed JSON, plus one exact-bytes test for the hook output |
| Fail-closed done-file protocol regressions | Contract tests already cover crash / no output / bad config; keep them unchanged across cutover |
| Cross-plugin coupling (`watch-pr` test imports `check.mjs`) | Replace with the `check` CLI contract in P3 |

## 6. Open questions

None. Decided 2026-11-20: Python ≥ 3.14 (D1; 3.11 considered and rejected), system Python for users and a
uv venv for development (D1c), pytest (D2), `notify.sh` → Python (D4a),
subagent-driven execution.
