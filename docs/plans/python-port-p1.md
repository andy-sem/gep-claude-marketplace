# Python Port P1 (destructive-guard contract tests) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P1 is **one package** (repo rule: one commit per work package). Tasks 1–5 do not commit; Task 6 makes the single commit.

**Goal:** Python tests that pin the behaviour of `destructive-guard` through its public entry points (`hooks/gate.sh`, `hooks/env-guard.sh`, the `check` CLI) and a shared JSON case corpus, green against the current JS (`GD_IMPL=js`), so P4–P9 can swap the implementation underneath without touching them. Also lands the P0 review leftovers.

**Architecture:** black-box tests drive subprocesses through the `impl` fixture (`testkit.impl.Impl`); the 344 rule cases move to `tests/cases/*.json` and run through `check --json` (verified 2026-11-20: all 344 give the same id through `check --json` from an empty project as through `classify`, with `GATE_STRICT` 0 and 1). Pure helpers with no CLI surface (`composeRules`, Jev prompt helpers) go through the P0 bridge and are retargeted in P4/P7. A threaded local HTTP server stands in for Jev.

**Tech Stack:** Python ≥ 3.14 stdlib (`subprocess`, `http.server`, `threading`, `concurrent.futures`, `json`), pytest, the P0 `testkit`, node (JS impl + bridge).

**Spec:** `docs/plans/python-port.md` (§3 strategy, P1 in §4, Review Focus); behaviour = the JS tests in `plugins/destructive-guard/test/{gate-hook,env-guard,check,destructive,gate-rules,packs,readme,jev-prompt}.test.mjs` + `plugins/destructive-guard/README.md`.

## Global Constraints

- Tests only: no change to `lib/*.mjs`, `hooks/*.sh`, `packs/`, `jev/` or any `test/*.test.mjs`. `node --test` suites stay green with unchanged counts (735 / 68).
- Every new test passes with `GD_IMPL=js` (default) — that is the exit criterion. Tests that cannot yet run with `GD_IMPL=py` are expected to fail under it; do not skip or xfail them.
- Contract tests start entry points only via `impl.gate_hook()`, `impl.env_guard()`, `impl.check()` and pass `impl.env()`; never `node`/`sys.executable` directly (bridge-based unit tests excepted).
- Every subprocess env is built by `testkit.envs.clean_env(...)`: the developer's own `GATE_*`, `TYPESAFE_*`, `CLAUDE_PROJECT_DIR` must never leak in.
- Public repo hygiene (`CLAUDE.md`): fictional tools (`cloudctl`, `dbhost`, `acmecloud`, `mcp__tracker__editIssue`, `mcp__db__execute_sql`), no named MCP servers, no source-project names, no Supabase/GCP.
- Hook output for an ask is exactly `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"<reason>"}}` with **no** trailing newline; pass = empty stdout, exit 0.
- Mapping: every JS test of the 8 files above gets a non-`todo` target in `plugins/destructive-guard/tests/PORTING.md`; rows of `config`, `gate-engine`, `gate-scripts`, `gate-jev` stay `todo` (P2).

## Review Focus

- Invalid UTF-8 / non-ASCII in hook stdin → JS replaces bad bytes and decides normally (`rm -rf \xff` → ask `rm-recursive-force`, `ls \xff` → pass, `rm -rf Für` → ask). Pinned in Task 2 (`test_non_utf8_stdin_decides_normally`).
- Exact hook bytes (no trailing newline, compact JSON, key order) → Task 2 `test_ask_output_exact_bytes`, for both a wrapper ask and an engine ask.
- A developer's shell with `GATE_CHECKS=…` or `GATE_JEV=1` exported → tests must not change outcome. Task 1 `test_clean_env_drops_gate_vars`.
- Jev mock that "hangs" must not hang the suite → handler waits on an `Event` set at fixture teardown, max 10 s (Task 1).
- Corpus run time: 344 CLI calls → run concurrently once per session (Task 4), target < 15 s locally.

---

### Task 1: Contract test kit + P0 leftovers

**Files:**
- Create: `testkit/envs.py`, `testkit/hook.py`, `testkit/check_cli.py`, `testkit/jev_mock.py`, `testkit/projects.py`, `tests/test_testkit_contract.py`
- Modify: `testkit/bridge.py`, `testkit/impl.py`, `testkit/pythons.py`, `testkit/stubs.py`, `tests/test_testkit_bridge.py`, `tests/test_testkit_impl.py`, `.github/workflows/test.yml`

**Interfaces (Produces):**
- `testkit.envs.clean_env(*overlays: Mapping[str, str]) -> dict[str, str]` — `os.environ` minus every key matching `^(GATE_|TYPESAFE_)` and `CLAUDE_PROJECT_DIR`, then each overlay applied in order.
- `Impl` additions: `interpreter_var: str` (`"GATE_INFRA_NODE"` / `"GATE_INFRA_PYTHON"`), `unavailable_reason: str` (`"unparsable: node unavailable"` / `"unparsable: python unavailable"`), `check_invocation(args: str) -> str` (js `node "/plugin/lib/check.mjs" <args>`, py `python3 "/plugin/lib/check.py" <args>`). `env()` for js raises `RuntimeError("node not found on PATH")` when `shutil.which("node")` is `None` (P0 minor 2).
- `testkit.pythons.require_new_python(env: Mapping[str, str]) -> str` — `find_python(env)`, then one cached version probe; `None` or < 3.14 → `RuntimeError("need Python >= 3.14, found <ver or nothing> at <path>; set GATE_INFRA_PYTHON")`. `Impl._python()` and `testkit/stubs.py`'s 3.14 check use it (P0 minor 4).
- `testkit.hook`: `bash_input(command: str, cwd: Path | str) -> str`, `mcp_input(tool: str, tool_input: dict, cwd: Path | str) -> str` (JSON strings like the JS `bash()`/`mcpCall()`); `HookResult(status: int, stdout: str)`; `run_hook(impl, stdin: str | bytes, *env: Mapping[str, str], cwd=None, timeout=30) -> HookResult` (env = `clean_env(impl.env(), {"GATE_JEV": "", "GATE_JEV_LOG": ""}, *env)`); `decision(stdout: str) -> dict` (the `hookSpecificOutput` object); `ASK_TEMPLATE` exact-bytes format string.
- `testkit.check_cli`: `run_check(impl, *args: str, env: Mapping[str, str] = {}, cwd=None) -> subprocess.CompletedProcess[str]` (env through `clean_env`); `check_call(impl, call: dict, env: Mapping = {}, cwd: Path | None = None) -> dict` — `call` is `{"bash": cmd}` or `{"mcp": tool, "input": {...}}`; runs `--json [--cwd cwd] -- cmd` or `--json --mcp tool <json>`; returns parsed JSON, asserts exit 0.
- `testkit.jev_mock.JevMock` (context manager; pytest fixture `jev` in root `conftest.py`, function-scoped): `.url` (`http://127.0.0.1:<port>/v1/systemone`), `.answer(probs: dict | None = None, *, kind="ok", status=None, question="cloud_change", usage=None)`, `.bodies: list[dict | None]`, `.hits: int`. Behaviour mirrors the JS mock in `gate-hook.test.mjs` (`ok` → 200 `{"answers": {question: {"type": "choice", "probabilities": probs}}, "usage": usage or {"input_tokens": 1000, "output_tokens": 10}}`; `status` → bare status; `malformed` → 200 body `{`; `hang` → wait on teardown `Event`, max 10 s). `ThreadingHTTPServer`, daemon thread.
- `testkit.projects.temp_project(base: Path, files: dict[str, str]) -> Path` (realpath'd dir with an empty `.git/`), `provision_project(base) -> Path` (the two-file cloudctl provision project from `gate-hook.test.mjs`).
- `testkit.probs(unrelated, read_only, cloud_or_data_change, destructive) -> dict` lives in `testkit/jev_mock.py`.

- [ ] **Step 1: Tests** in `tests/test_testkit_contract.py`: `test_clean_env_drops_gate_vars` (monkeypatch `GATE_CHECKS=nope`, `TYPESAFE_API_KEY=x`, `CLAUDE_PROJECT_DIR=/x` → absent; overlay wins); `test_jev_mock_records_and_answers` (POST via `urllib.request` → JSON answer with given question key, `hits == 1`, body parsed); `test_jev_mock_status_and_malformed`; `test_jev_mock_hang_released_on_exit` (client with 0.2 s timeout times out; leaving the context returns in < 2 s); `test_temp_project_has_git_root`. Extend `tests/test_testkit_bridge.py`: `test_error_shape_needs_exit_1` (factor `_decode(returncode: int, stdout: str, stderr: str, what: str) -> Any` out of `bridge()`; `_decode(0, '{"$error": {"name": "X", "message": "m"}}', "", …)` returns the dict as data, `_decode(1, same)` raises `BridgeError`, `_decode(1, "oops", "trace", …)` raises `RuntimeError` containing `trace`), `test_missing_node_is_runtime_error` (monkeypatch `PATH` to empty dir → `RuntimeError`), `test_set_is_encoded_as_list` (`bridge("gate-engine", "parseRules", {"rules": []})`: if any field of the result is a JS `Set`/`Map` it arrives as list/dict — find one with `grep -n 'new Set\|new Map' plugins/destructive-guard/lib/gate-engine.mjs`; if no export returns one, omit this test and say so in the report). Extend `tests/test_testkit_impl.py`: `test_js_env_without_node_raises`, `test_impl_interpreter_fields`, `test_require_new_python_rejects_old` (fake `python3` printing 3.9 on `PATH`).
- [ ] **Step 2:** `uv run pytest tests -q` → new tests fail (missing modules/attributes).
- [ ] **Step 3:** Implement the interfaces above. `bridge.py`: `$error` only when `returncode == 1` (P0 minor 1); `FileNotFoundError` → `RuntimeError`. Annotate `Impl._script(base: Path, …)` (P0 minor 6).
- [ ] **Step 4: CI (P0 minor 3).** In the `python` job replace the uv-managed interpreter with `actions/setup-python@v5` (`python-version: ${{ matrix.python }}`, matrix `["3.14", "3.x"]`), then `uv sync --python "$(python -c 'import sys;print(sys.executable)')"`, keep the 3.9 `OLD_PYTHON` step. This puts the tested interpreter on `PATH` as `python3`/`python3.X`, so `find_python` sees it on both legs.
- [ ] **Step 5:** `uv run pytest tests -q` → pass; `uv run ruff check .` clean.

### Task 2: Gate hook contract (no Jev)

**Files:** Create `plugins/destructive-guard/tests/test_gate_hook.py`, `plugins/destructive-guard/tests/fixtures/rules.json` (byte copy of `test/fixtures/rules.json`).

**Interfaces:** Consumes Task 1 (`run_hook`, `decision`, `bash_input`, `temp_project`, `provision_project`, `impl`). Produces fixtures in `plugins/destructive-guard/tests/conftest.py`: `tf_rules(tmp_path_factory) -> Path` (the JS `before()` file: one `tf` rule on `terraform apply`, `inertPrograms: ["grep"]`), `bad_rules -> Path` (`{not json`), `SHIPPED = DG / "tests/fixtures/rules.json"`. Default hook env for this file = `{"GATE_RULES": tf_rules, "CLAUDE_PROJECT_DIR": REPO}` (the JS tests use the deprecated `GATE_RULES`; keep it).

- [ ] **Step 1:** Port the 14 non-Jev tests of `gate-hook.test.mjs` (the 13 in lines 66–255 plus "the gate hook stays registered for Bash and every MCP tool only") one Python test each, same inputs and assertions. Impl-dependent values come from `impl`: "node unavailable" → `test_interpreter_unavailable_asks` sets `{impl.interpreter_var: "/nonexistent"}` and expects `impl.unavailable_reason`; the two fake-engine tests write executable bash fakes and pass them via `impl.interpreter_var`. Add `test_fixture_copy_matches_js` (while `test/fixtures/rules.json` exists, bytes equal).
- [ ] **Step 2: Review-focus tests.** `test_ask_output_exact_bytes`: (a) engine ask — default packs (no `GATE_RULES`), `git push -f`, cwd tmp → stdout `== '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"git-push-force: gated invocation"}}'`; (b) wrapper ask — `impl.unavailable_reason` with the same template. `test_non_utf8_stdin_decides_normally`: stdin bytes for `rm -rf \xff` → ask `rm-recursive-force: gated invocation`; `ls \xff` → `""`; `rm -rf Für` → ask.
- [ ] **Step 3:** `uv run pytest plugins/destructive-guard/tests/test_gate_hook.py -v` → all pass on JS.

### Task 3: Gate hook contract with Jev

**Files:** Create `plugins/destructive-guard/tests/test_gate_hook_jev.py`.

**Interfaces:** Consumes `jev` fixture, `probs`, Task 2 fixtures. Jev env = `{"GATE_RULES": tf_rules, "CLAUDE_PROJECT_DIR": REPO, "GATE_JEV": "1", "GATE_JEV_LOG": "", "TYPESAFE_API_KEY": "test-key", "GATE_JEV_URL": jev.url, "GATE_JEV_TIMEOUT_MS": "5000", "GATE_JEV_PROMPT": "cloud-change"}`; `shipped = {"GATE_RULES": SHIPPED}`; tool names `mcp__plugin_dbhost_dbhost__execute_sql`, `mcp__cloudctl__run_cloudctl_command`, `mcp__tracker__editIssue`, `mcp__browser__click`.

- [ ] **Step 1:** Port the 29 Jev tests of `gate-hook.test.mjs` (from "GATE_JEV unset -> rules-only output" to "jev audit log…", minus the hooks.json test owned by Task 2), one Python test each, same inputs, probabilities, env and assertions (hits, bodies, `state.scripts`/`notes`/`input` contents, the 64 KB caps, the audit-log record). Unreachable URL stays `http://127.0.0.1:1/v1/systemone`.
- [ ] **Step 2:** `uv run pytest plugins/destructive-guard/tests/test_gate_hook_jev.py -v` → all pass on JS; note wall time in the report.

### Task 4: Rule case corpus

**Files:** Create `plugins/destructive-guard/tests/cases/destructive.json`, `plugins/destructive-guard/tests/cases/gate_rules.json`, `plugins/destructive-guard/tests/test_corpus.py`, `plugins/destructive-guard/tests/test_rule_kinds.py`.

**Interfaces:**
- Corpus file format: `{"source": "<js file>", "env": {…}, "cases": [{"bash": "<cmd>", "expect": "<rule id>" | null} | {"mcp": "<tool>", "input": {…}, "expect": …}]}`. `env` for `destructive.json` is `{}`; for `gate_rules.json` `{"GATE_CHECKS": "none", "GATE_RULES_FILE": "<abs path filled at load from tests/fixtures/rules.json>"}` — store `"GATE_RULES_FILE": "@fixture:rules.json"` and resolve in the loader. `gate_rules.json` also holds the 4 commands of "wrangler, pulumi, cf-apply scripts and git push are not gated" as `expect: null` cases with `"group": "not-gated"`.
- `test_corpus.py`: `load_corpus(name: str) -> tuple[dict, list[dict]]`; module-scoped fixture `corpus_results` (impl from `select_impl("destructive-guard", os.environ)`, since `impl` is function-scoped) runs **every** case through `check_call` once, concurrently (`ThreadPoolExecutor(max_workers=os.cpu_count())`), cwd = one empty `temp_project`; result per case = `source` if `decision == "ask"` else `None`.

- [ ] **Step 1:** Generate both JSON files from the JS `cases` arrays with a throwaway node script (not committed): slice the `const cases = [...]` literal, evaluate it with `bash`/`mcp` helpers, write JSON. Drop `currentBranch` (unused by the engine).
- [ ] **Step 2: Tests.** `test_corpus_sizes`: destructive 150 cases, gate_rules 194 + 4 `not-gated`. `test_destructive_case` / `test_gate_rules_case` parametrised over the cases (ids = the JS label: command, or `<tool> <json input>`), assert `corpus_results[...] == expect`. `test_every_destructive_rule_has_an_asking_case` (ids from `packs/destructive.json` ⊆ corpus expects). `test_destructive_rules_do_not_make_script_scan_ask` (via `check_call` with `--cwd` = project holding `build.sh` = `rm -rf dist\ngit push\n`; and `bash /usr/local/bin/x.sh` → none).
- [ ] **Step 3: `test_rule_kinds.py`.** Port the 6 inline-rule tests of `destructive.test.mjs` (whenFlags, unlessFlags, dynamicArgs, whenArgs, validation, mcp-pattern) through `check_call` with `{"GATE_CHECKS": "none", "GATE_RULES_FILE": <tmp file with {"rules": [rule]}>}`: rule id → `source`; full reason (`"t: gated invocation"`, `"t: dynamic argument"`, `"m: anything"`) → `reason`; `RulesError` → `decision == "ask"` and `source == "gate-config"`.
- [ ] **Step 4:** `uv run pytest plugins/destructive-guard/tests/test_corpus.py plugins/destructive-guard/tests/test_rule_kinds.py -q --durations=5` → pass; corpus < 15 s.

### Task 5: check CLI, env guard, packs, README, Jev prompts

**Files:** Create `plugins/destructive-guard/tests/{test_check,test_env_guard,test_packs,test_readme,test_jev_prompt}.py`.

**Interfaces:** Consumes Task 1–2 helpers, `bridge`.

- [ ] **Step 1: `test_check.py`** — the 11 tests of `check.test.mjs` through the CLI: parseArgs cases via `--json` output fields (`command`, `tool`, `input`; `--` joins args; no args/`--config` → config JSON has `packs`); usage errors → exit 2 and stdout `^usage error: `; `checkCall` cases via `check_call`; `effectiveConfig` via `--config --json`; CLI text output (`decision: ask`, `source: +git-push-force`, `packs: +base, destructive`, `api key \[set\]`, key never printed); "documented invocations" through `run_hook` with default packs and `impl.check_invocation(...)` for the 5 invocations → stdout `""`; `--cwd` script resolution; relative `GATE_RULES_FILE` against the git root of `--cwd`.
- [ ] **Step 2: `test_env_guard.py`** — the 3 tests (exit 2 for `.env`, `.env.local`, `apps/web/.env.production` on Read/Edit/Write; 0 for `.env.example`, ordinary files, `""`; without `jq`: `PATH` = tmp dir with symlinks to `cat`, `sed`, `head` only, run with `/bin/bash`).
- [ ] **Step 3: `test_packs.py`** — via `bridge("gate-engine", …)`: `composeRules`, `loadPacks`, `packPath`, `DEFAULT_PACKS`; `RulesError` = `BridgeError` with `.name == "RulesError"`. The last test ("without GATE_RULES the hook loads the default packs") via `run_hook`. Fixture from `tests/fixtures/rules.json`. Mark the bridge tests with a module docstring line `# retarget to destructive_guard in P5`.
- [ ] **Step 4: `test_readme.py`** — env-var scan of `lib/` **recursively** (`*.mjs` and `*.py`) and `hooks/`, internal set `{GATE_RUN, GATE_DONE_FILE, GATE_INFRA_NODE, GATE_INFRA_PYTHON}`, ≥ 10 names, every one appears in README as `` `NAME` ``; every `packs/*.json` and `jev/*.json` stem appears in backticks (P0 minor 5).
- [ ] **Step 5: `test_jev_prompt.py`** — pure tests via `bridge("gate-jev", …)` (`DEFAULT_PROMPT`, `readJevConfig`, `builtinPrompt`, `validatePrompt`, `jevDecision`, `promptFromEnv`; `JevConfigError` by `BridgeError.name`); the built-in prompt hygiene test reads `jev/*.json` directly (no `mcp__\w`, none of `jira|atlassian|chrome|cloudflare|wrangler|supabase|gcloud|google`, case-insensitive). "askJev sends the destructive question" through `run_check(impl, "--json", "--jev", "--", "rm -rf ~/work", env={GATE_JEV: "1", TYPESAFE_API_KEY: "k", GATE_JEV_URL: jev.url})` with `jev.answer(probs d(0.05,0.05,0.9), question="destructive")`: request `questions` keys `== ["destructive"]`, `state.context.policy` == builtin destructive policy, result `source == "jev"`.
- [ ] **Step 6:** `uv run pytest plugins/destructive-guard/tests -q` → pass.

### Task 6: Map, verify, commit

- [ ] **Step 1:** Fill `plugins/destructive-guard/tests/PORTING.md`: every row of the 8 P1 files → `tests/<file>.py::<test>` (parametrised JS template rows → the parametrised Python test). `uv run pytest tests/test_porting.py -v` → pass.
- [ ] **Step 2:** `node --test 'plugins/destructive-guard/test/*.test.mjs'` (735 pass) and `node --test 'plugins/gated-dev-simple-workflow/test/*.test.mjs'` (68 pass); `uv run pytest` → all pass, list skips; `uv run ruff check .` clean; `claude plugin validate .` ok. Run `GD_IMPL=py uv run pytest plugins/destructive-guard/tests -q` and report the count of failures (expected: the contract tests fail, since `check.py`/`gate_main.py` are placeholders — this is information, not a gate).
- [ ] **Step 3:** In `docs/plans/python-port.md` §4 mark P1 done (link this file) and record: corpus runs through `check --json` (344 cases verified equal to `classify`), JS invalid-UTF-8 behaviour pinned, CI uses `setup-python` (`3.14`, `3.x`).
- [ ] **Step 4:** One commit, message `Python port P1: destructive-guard contract tests and case corpus`, short body, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
