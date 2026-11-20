# Python Port P2 (destructive-guard units) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P2 is **one package** (repo rule: one commit per work package). Tasks 1–5 do not commit; Task 6 makes the single commit.

**Goal:** Python tests for the 120 still-`todo` JS tests of `config`, `gate-engine`, `gate-scripts` and `gate-jev`, green against the current JS (`GD_IMPL=js`), so P4–P7 can port those modules under them.

**Architecture:** same three layers as P1. Anything with a CLI or hook surface goes through it (`check --json`, `gate.sh`) and survives cutover unchanged. The engine's 189 classify cases become a third corpus, `tests/cases/gate_engine.json`. Pure helpers go through the P0 bridge, which gains nested calls (so parsed rules never cross the JSON boundary) and a batch mode (one node process for many calls). `askJev`/`runJev` tests that inject `fetchImpl` become `gate.sh` tests against the P1 Jev mock, which learns answer sequences, `retry-after`, raw bodies and request headers. Where a P1 test already pins the same behaviour, the PORTING row points to it instead of a new test.

**Tech Stack:** Python ≥ 3.14 stdlib, pytest, the P0/P1 `testkit`, node (JS impl + bridge).

**Spec:** `docs/plans/python-port.md` (§3 strategy, P2 in §4); behaviour = `plugins/destructive-guard/test/{config,gate-engine,gate-scripts,gate-jev}.test.mjs`. Pattern and test kit: `docs/plans/python-port-p1.md`.

## Global Constraints

- Tests only: no change to `lib/*.mjs`, `hooks/*.sh`, `packs/`, `jev/` or any `test/*.test.mjs`. `node --test` suites stay green with unchanged counts (735 / 68).
- Exit criterion: no `todo` row left in `plugins/destructive-guard/tests/PORTING.md`, `uv run pytest` green with `GD_IMPL=js` (default). Tests that cannot run with `GD_IMPL=py` yet are expected to fail under it; do not skip or xfail them.
- Contract tests start entry points only via `impl.gate_hook()`, `impl.env_guard()`, `impl.check()` (through `run_hook`, `run_check`, `check_call`); every subprocess env goes through `testkit.envs.clean_env`.
- Bridge-based test modules carry the docstring line `# retarget to destructive_guard in P<n>` (config → P4, gate-engine → P5, gate-scripts → P6, gate-jev → P7).
- Public repo hygiene (`CLAUDE.md`): fictional tools only (`cloudctl`, `blobctl`, `dbtool`, `dbhost`, `acmecloud`, `deployctl`), made-up MCP names, no Supabase/GCP, no source-project names. Copy JS inputs verbatim; they already comply.
- Do not touch the untracked `docs/plans/lean-gate-model.md` or the unstaged `.gitignore` change; stage files by name.

## Review Focus

- Bridge batch with one failing call → must raise `BridgeError` for that call, not return a half list or hide the error (Task 1 `test_bridge_many_raises_on_error`).
- Engine corpus through `check --json` vs `classify()` → loose/strict and script scanning could change ids; the corpus env sets `GATE_STRICT=1`, and Task 2 Step 1 verifies all 189 ids equal `classify` before the JSON is committed.
- Jev mock answer sequence → the last answer must repeat so a retry loop does not get an empty or stale answer (Task 1 `test_jev_mock_sequence_repeats_last`).
- Wall time: ~200 `collectScripts` calls at ~120 ms per node spawn → Task 4 batches them per test; target for the whole P2 suite < 30 s locally.
- JS RegExp results (`globToRegExp`, `scriptPatterns`) compared in Python → `testkit.bridge.js_regexp` compiles the source with `re`; a source Python cannot compile fails the test loudly (no fallback).

---

### Task 1: Test kit — nested bridge calls, batch, regexps, Jev mock

**Files:** Modify `testkit/_bridge.mjs`, `testkit/bridge.py`, `testkit/jev_mock.py`, `tests/test_testkit_bridge.py`, `tests/test_testkit_contract.py`.

**Interfaces (Produces):**
- `testkit.bridge.call(module: str, export: str, *args) -> dict` — returns the marker `{"$call": [module, export, [args...]]}`. `_bridge.mjs` replaces any marker anywhere in the argument tree (depth-first) by the awaited result of that call before the outer call. Retarget rule: `call(m, f, *a)` becomes `f(*a)`.
- `testkit.bridge.bridge_many(calls: list[tuple[str, str, list]]) -> list[Any]` — one node process (`_bridge.mjs --batch`, stdin = JSON list of `[module, export, args]`), results in order; any call that throws → exit 1 and `{"$error": {..., "index": i}}`, raised as `BridgeError`.
- `testkit.bridge.js_regexp(value: dict) -> re.Pattern` — `{"$regexp": src, "flags": f}` → `re.compile(src, re.I if "i" in f else 0)`.
- `JevMock` additions: `.headers: list[dict[str, str]]` (lower-cased request headers, reset with `bodies`); `answer(..., retry_after: str | None = None, body: dict | None = None)` — `kind="raw"` sends 200 with `body` as JSON; `retry_after` adds the `retry-after` header to a `status` answer; `sequence(*answers: dict)` — each dict is `answer()` kwargs, served in order, the last repeating; resets recorded requests.

- [ ] **Step 1: Tests.** `tests/test_testkit_bridge.py`: `test_nested_call_args` (`bridge("gate-engine", "composeRules", [call("gate-engine", "packPath", "base")])["rules"]` is a non-empty list); `test_bridge_many_in_order` (`bridge_many([("gate-engine", "packPath", ["base"]), ("config", "DEFAULT_CHECKS", [])])` == `[<path>, ["destructive"]]`); `test_bridge_many_raises_on_error` (second call `("gate-engine", "loadRules", ["/nope.json"])` → `BridgeError` with `.name == "RulesError"`); `test_js_regexp` (`js_regexp(bridge("gate-scripts", "globToRegExp", "a/*.js")).search("a/b.js")` truthy). `tests/test_testkit_contract.py`: `test_jev_mock_records_headers`, `test_jev_mock_retry_after_and_raw` (status 429 with `retry-after: 0`; raw body `{"answers": {}}`), `test_jev_mock_sequence_repeats_last` (sequence 429, ok → three POSTs give 429, 200, 200).
- [ ] **Step 2:** `uv run pytest tests -q` → the new tests fail.
- [ ] **Step 3:** Implement the interfaces above; `bridge()` keeps its signature.
- [ ] **Step 4:** `uv run pytest tests -q` → pass; `uv run ruff check .` clean.

### Task 2: gate-engine (15 rows)

**Files:** Create `plugins/destructive-guard/tests/fixtures/engine_rules.json` (the `rules` object of `gate-engine.test.mjs`, verbatim), `plugins/destructive-guard/tests/cases/gate_engine.json`, `plugins/destructive-guard/tests/test_gate_engine.py`. Modify `plugins/destructive-guard/tests/test_corpus.py`.

**Interfaces:** Consumes Task 1, P1 `test_corpus.py`. Corpus `gate_engine.json`: `{"source": "test/gate-engine.test.mjs", "env": {"GATE_CHECKS": "none", "GATE_RULES_FILE": "@fixture:engine_rules.json", "GATE_STRICT": "1"}, "cases": [...]}`; case kinds `bash`, `mcp` + `input`, and new `{"hook": {"tool_name": …, "tool_input": …}, "expect": …}` for the 2 non-`mcp__` calls (`Bash` without command, `Read`), which `corpus_results` sends through `run_hook` (`cwd` added) like P1's `Read` cases.

- [ ] **Step 1: Generate and verify the corpus** with a throwaway node script (not committed): eval the `cases` literal, write JSON (189 cases: 177 bash, 10 mcp, 2 hook), and check that every case gives the same first reason segment through `check --json` from an empty temp project with the corpus env as through `classify(…, loadRules(fixture))`. Any mismatch stops the task; report it.
- [ ] **Step 2: Corpus tests.** Add `"gate_engine"` to `CORPORA`; `test_corpus_sizes` asserts 189; `test_gate_engine_case` parametrised like the other two (ids = JS label). Expected values are the reason's first segment (`"unparsable"`, `"inert program with command flag"` included), so for this corpus `corpus_results` stores `reason.split(":")[0]`, not `source` — keep the P1 corpora on `source`.
- [ ] **Step 3: `test_gate_engine.py`** (module docstring: `# retarget to destructive_guard in P5` for the bridge parts):
  - `test_allowlist_reasons_name_the_write_verb`, `test_dynamic_arguments_name_the_reason`, `test_shell_reading_stdin_reason` — `check_call(..., env=corpus env)["reason"]` equals the exact JS strings.
  - `test_non_object_input_fails_closed` — `run_hook` with stdin `null` and `"x"` → reason starts `unparsable:`.
  - `test_split_command` — `bridge("gate-engine", "splitCommand", 'a b && c "d e"; f') == [["a","b"],["c","d e"],["f"]]`; `echo "x` and `(echo x` → `BridgeError` name `UnparsableError`.
  - `test_load_rules_runners`, `test_load_rules_bad_config`, `test_load_rules_legacy_and_removed_kinds`, `test_load_rules_inert_unsafe_flags` — `bridge("gate-engine", "loadRules", path)` on tmp files, same inputs as JS; `RulesError` by `BridgeError.name`. The legacy-runner assertion reads `loadRules(engine_rules.json)["runners"]`.
  - CLI rows (`gate-engine.mjs` run as a script) → through `run_hook` with `{"GATE_RULES": engine_rules.json, "CLAUDE_PROJECT_DIR": REPO}`: `test_cli_gated_command_asks` (reason `^dbtool:`), `test_cli_non_gated_prints_nothing`, `test_cli_subagent_call_still_asks` (`agent_id: "agent-123"` in stdin), `test_cli_broken_rules_asks_gate_config` (a `Read` call), `test_cli_unparsable_stdin_asks`.
- [ ] **Step 4:** `uv run pytest plugins/destructive-guard/tests/test_corpus.py plugins/destructive-guard/tests/test_gate_engine.py -q --durations=5` → pass.

### Task 3: config (26 rows)

**Files:** Create `plugins/destructive-guard/tests/test_config.py`.

**Interfaces:** Consumes Task 1 (`bridge`, `BridgeError`), `check_call`, `run_hook`, `impl.env_guard()`, `temp_project`. `extra_rules` fixture = the JS `deployctl` rules file (`cli-gated`, `programs: ["deployctl"]`, `gatedPrefixes: [["release"]]`).

- [ ] **Step 1: `readConfig` / `availablePacks` / `DEFAULT_CHECKS`** via `bridge("config", "readConfig", env, opts)` — the first 11 JS tests, same inputs and expected dicts (`log: None` for JS `null`). `ConfigError` → `BridgeError.name == "ConfigError"`, message regexes as in JS. The cwd/git-root test uses `temp_project` with `.claude/rules.json` and `apps/web/`.
- [ ] **Step 2: `buildRules` + strict** through `check_call` with env instead of `buildRules(readConfig(env))`: rule id via `reason.split(":")[0]`, `None` when `decision == "none"`. Unknown `GATE_DISABLE_RULES` id → `source == "gate-config"` and reason contains `unknown rule id "git-push-forse"`; missing file → `gate-config`; duplicate id → reason contains `duplicate rule id`. Strict test: JS `classify` default strict = `GATE_STRICT=1`, `{strict: false}` = `GATE_STRICT=0`; the empty-command row goes through `run_hook` with stdin `{"tool_name":"Bash","tool_input":{}}` and `GATE_STRICT=0` → `unparsable:`.
- [ ] **Step 3: hook rows** (7 tests) through `run_hook` with stdin `bash_input(cmd, tmp)`, same envs and assertions; the relative-file test runs with `cwd=<project>/apps/web` once with `CLAUDE_PROJECT_DIR` and once without; the `GATE_LOG` tests read the JSONL as JS does.
- [ ] **Step 4: env-guard rows** (2 tests) through `impl.env_guard()` like P1 `test_env_guard.py`, with the JS file lists and `GATE_ENV_GUARD` / `GATE_ENABLED` values.
- [ ] **Step 5:** `uv run pytest plugins/destructive-guard/tests/test_config.py -q` → pass.

### Task 4: gate-scripts (28 rows)

**Files:** Create `plugins/destructive-guard/tests/test_gate_scripts.py` (docstring `# retarget to destructive_guard in P6`).

**Interfaces:** Consumes Task 1 (`call`, `bridge_many`, `js_regexp`), `temp_project`, `SHIPPED`. Local helpers: `RULES = call("gate-engine", "loadRules", str(SHIPPED))`; `collect_many(root: Path, commands: list[str], cwd: Path | None = None) -> list[dict]` = one `bridge_many` of `("gate-scripts", "collectScripts", [cmd, RULES, {"cwd": str(cwd or root), "root": str(root)}])`; `paths(c) -> list[str]`; `scan_many(root, commands) -> list[str | None]` = `scanScripts(call(collectScripts …), RULES)` per command, `reason` or `None`.

- [ ] **Step 1:** One Python test per JS test, same project files, commands and expected lists; loops over commands become one `collect_many` call. `findProjectRoot` and `globToRegExp` via `bridge`/`js_regexp`; `scanScripts(undefined)` → `bridge("gate-scripts", "scanScripts", None, RULES)` is `None`. The `loadRules` scriptPatterns test checks `js_regexp(ok["scriptPatterns"][0]).search("aab")` and the shipped values (9 patterns, the 3 exempt globs). Symlink and outside-project tests create the outside dir with `tmp_path_factory`, resolved.
- [ ] **Step 2:** `uv run pytest plugins/destructive-guard/tests/test_gate_scripts.py -q --durations=5` → pass; note wall time.

### Task 5: gate-jev (51 rows)

**Files:** Create `plugins/destructive-guard/tests/test_jev_units.py` (bridge, docstring `# retarget to destructive_guard in P7`), `plugins/destructive-guard/tests/test_jev_http.py` (hook + mock).

**Interfaces:** Consumes Task 1 (`call`, `bridge`, `bridge_many`, extended `JevMock`), P1 `test_gate_hook_jev.py` fixtures pattern (copy `base_env`/`shipped`/`run_jev`-style fixtures into `test_jev_http.py` or move shared ones into `tests/conftest.py`; do not import between test modules). `CFG` = the JS `cfg` with `logPath` omitted and `prompt = call("gate-jev", "builtinPrompt", "cloud-change")`.

- [ ] **Step 1: `test_jev_units.py`** — pure rows, same inputs/expectations: `redact` (9), `readJevConfig` (7; `logPath` arrives as `None`, `prompt` compared to `bridge("gate-jev", "builtinPrompt", "destructive")`), `jevDecision` (6), `parseAnswer` (2; JS `undefined` field → key removed), `buildState` (3), `redactScript` / `redactMcpInput` (5). Batch each test's calls with `bridge_many`.
- [ ] **Step 2: `test_jev_http.py`** — `askJev`/`runJev` rows through `run_hook` with env `{"GATE_JEV": "1", "TYPESAFE_API_KEY": "key-123", "GATE_JEV_URL": jev.url, "GATE_JEV_PROMPT": "cloud-change", "GATE_JEV_LOG": <tmp>/audit.jsonl, ...}`; error kinds and latency/usage are read from the audit log (`outcome` `fallback: http 500` / `fallback: timeout` / `fallback: network` / `fallback: malformed`, `latencyMs`, `usage`). New tests: `test_request_shape` (headers `authorization == "Bearer key-123"`, body `model`, `state.context` keys, single `cloud_change` question, its instructions, criteria keys, every needle of the JS list in the examples, no `local_write`), `test_error_has_latency`, `test_usage_null_when_absent`, `test_non_retryable_http_error`, `test_retries_429_then_succeeds` (sequence 429 `retry-after: 0`, ok → `hits == 2`, decision from the ok answer), `test_retry_after_over_budget_gives_up` (`GATE_JEV_TIMEOUT_MS=200`, 529 `retry-after: 10` → `hits == 1`), `test_hang_times_out` (`kind="hang"`, `GATE_JEV_TIMEOUT_MS=50` → outcome `fallback: timeout`, hook returns in < 5 s), `test_network_failure` (URL `http://127.0.0.1:1/v1/systemone`), `test_malformed_bodies` (`kind="malformed"` and raw `{"answers": {}}`), `test_env_reference_never_sent` (`cat .env` with a rule ask → `hits == 0`, rule result stands), `test_undecided_keeps_rule_result`, `test_no_rule_opinion_asks_for_bash_and_mcp`.
- [ ] **Step 3: map instead of duplicating** — rows whose behaviour a P1 test already pins with the same inputs map to it: failure modes → `tests/test_gate_hook_jev.py::test_jev_failures_give_rule_result`; lift → `test_read_only_097_lifts_rule_and_script_asks`; `canLift` → `test_can_lift_0_keeps_rule_asks_jev_still_adds`; Bash scripts payload → `test_script_request_carries_redacted_script`; MCP payload/cut note → `test_mcp_calls_send_tool_name_and_redacted_input`; audit log → `test_audit_log_records_tool_usage_latency`. Before mapping, read the P1 test and confirm it asserts what the JS test asserts (both Bash and MCP where the JS covers both); where it does not, add the missing assertion as a new test in `test_jev_http.py` instead.
- [ ] **Step 4:** `uv run pytest plugins/destructive-guard/tests/test_jev_units.py plugins/destructive-guard/tests/test_jev_http.py -q --durations=5` → pass.

### Task 6: Map, verify, commit

- [ ] **Step 1:** Fill every `todo` row of `config`, `gate-engine`, `gate-scripts`, `gate-jev` in `plugins/destructive-guard/tests/PORTING.md` (the classify template row → `tests/test_corpus.py::test_gate_engine_case`). `grep -c '| todo |' plugins/destructive-guard/tests/PORTING.md` → `0`; `uv run pytest tests/test_porting.py -q` → pass.
- [ ] **Step 2:** `node --test 'plugins/destructive-guard/test/*.test.mjs'` (735 pass), `node --test 'plugins/gated-dev-simple-workflow/test/*.test.mjs'` (68 pass), `uv run pytest` (all pass, list skips), `uv run ruff check .`, `claude plugin validate .`. Report `GD_IMPL=py uv run pytest plugins/destructive-guard/tests -q` failure count (information only).
- [ ] **Step 3:** `docs/plans/python-port.md` §4: mark P2 done (link this file); record the bridge `call`/`bridge_many` additions and the third corpus.
- [ ] **Step 4:** One commit by file name, message `Python port P2: destructive-guard unit tests via bridge and contract`, short body, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
