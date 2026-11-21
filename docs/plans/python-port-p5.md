# Python Port P5 (destructive-guard `gate_engine`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P5 is **one package** by default. It is the largest and riskiest package; if Task 2 (tokenizer) alone exceeds ~600 lines of diff, split into **P5a** (tokenizer + normalisation, Tasks 1–3) and **P5b** (rule evaluation + `classify`, Tasks 4–6), one commit each, and record the split in `docs/plans/python-port.md` §4.
> Re-checked against the committed P1–P4 code (2026-11-20); adjustments are listed under "Adjustments at execution" at the end.

**Goal:** `destructive_guard.gate_engine`: the hand-written shell tokenizer (`split_command`, nested shells, substitutions, heredocs), wrapper/runner unwrapping (`sudo`, `env`, `xargs`, `bash -c`, `npx`, `pnpm exec`, …), rule evaluation (all rule kinds, MCP rules) and `classify`. All three case corpora (P1 `destructive`/`gate_rules` + P2 `gate_engine`, ~533 cases) pass through the Python `classify` in-process.

**Architecture:** port `gate-engine.mjs` section by section in its own order (tokenizer → normalisation → evaluation → `classify`), each section test-first. The tokenizer stays hand-written (no `shlex`, risk table §5). `gate()` (script scan + Jev) and the CLI entry are **not** in this package: `gate()` lands in P8 once `gate_scripts` (P6) and `gate_jev` (P7) exist; the hook entry is `gate_main.py` (P8). The P4 `rules` module is re-exported here.

**Tech Stack:** Python ≥ 3.14 stdlib (`re`, `dataclasses` optional), pytest.

**Spec:** `lib/gate-engine.mjs` (sections "Shell tokenizer", "Normalization and rule evaluation", `classify`); tests `tests/test_gate_engine.py`, `tests/test_rule_kinds.py`, `tests/test_corpus.py`, `tests/cases/*.json`; README §Rules.

**Paths** are relative to `plugins/destructive-guard/` unless they start with `docs/` or `testkit/`.

## Global Constraints

- Conventions of `docs/plans/python-port-p4.md` §Conventions (naming, JS-shaped data, error class names, retarget rule, regex compile helper).
- No change to `lib/*.mjs`, `hooks/*`, `packs/`, `jev/`, JS tests; node suites green (735 / 68). No change to `tests/cases/*.json` content (the corpus is the spec).
- Exit criterion: every corpus case gives the JS id through Python `classify` (both `strict` values where the corpus env says so); `tests/test_gate_engine.py` has no bridge left; `uv run pytest` green.
- Keep the module free of I/O at import time (latency, P8): no pack loading, no `gate_jev` import at top level.
- Public repo hygiene as in `CLAUDE.md`.

## Review Focus

- Tokenizer edge cases that JS handles by index arithmetic: `$'…'` ANSI-C quotes, `${…}` with nested `}` in quotes, backticks inside double quotes, heredoc `<<-` tab stripping and quoted delimiters, comments vs `#` inside words, `\` line continuations. Each must have a corpus case or a unit test; add a unit test where none exists.
- `DYN` placeholder (`"\u0000"`) must survive as a single code point in Python strings and never reach a reason string.
- `MAX_DEPTH = 8` nesting → `unparsable`, not `RecursionError`.
- Loose mode (`strict=False`): the module-level JS flag becomes an explicit parameter passed down, not a global (thread-safety, test isolation).
- Reasons are byte-identical to JS (`<id>: <detail>`), including the allowlist write-verb text and "inert program with command flag".

---

### Task 1: Corpus leg in-process

**Files:** Modify `tests/test_corpus.py`; create `tests/_corpus_py.py` (helper, not a test module).

**Interfaces (Produces):** `classify_case(corpus_env: dict, case: dict) -> str | None` — builds rules with `config.build_rules(config.read_config(env))` (cached per corpus), calls `gate_engine.classify(input, rules, strict=...)`, returns the same field the contract leg compares (`source` for P1 corpora, first reason segment for `gate_engine`). `hook` cases with non-`mcp__`/non-`Bash` tools go through `classify` too.

- [ ] **Step 1:** Add `test_<corpus>_case_py` parametrised next to each contract test, same ids. They fail (no `classify`) — expected red bar for the package.

### Task 2: Tokenizer

**Files:** Create `lib/destructive_guard/gate_engine.py` (tokenizer section), `tests/test_tokenizer.py`.

**Interfaces (Produces):** `UnparsableError`, `split_command(cmd: str) -> list[list[str]]`, internal `scan_list`, `find_backtick_end`, `find_brace_end`, `extract_subs`, `parse_shell`, `nested_strings`, `split_inner`, `basename`.

- [ ] **Step 1:** Retarget `test_split_command` (P2). Add a table test `test_split_command_cases` built once from the JS: a throwaway node script (not committed) runs `splitCommand` over every Bash command in the three corpora and writes `tests/fixtures/split_command.json` (`[[cmd, tokens | {"error": name}]]`); commit the fixture. This pins the tokenizer on ~500 real inputs before evaluation exists.
- [ ] **Step 2:** Port, run until both pass.

### Task 3: Normalisation

**Files:** Modify `lib/destructive_guard/gate_engine.py`, `tests/test_tokenizer.py`.

**Interfaces (Produces):** `strip_options`, `split_words`, `strip_version`, `strip_wrappers(raw_tokens, rules)`, `shell_script_index(tokens)`, `nested_shell_string(raw_tokens, rules)`, `normalize(raw_tokens, rules)`.

- [ ] **Step 1:** Fixture as in Task 2 for `stripWrappers` / `nestedShellString` / `shellScriptIndex` (exported in JS) over the corpus commands' simple commands, with the shipped default rules. Commit `tests/fixtures/normalize.json`.
- [ ] **Step 2:** Port, pass.

### Task 4: Rule evaluation (CLI rules)

**Files:** Modify `lib/destructive_guard/gate_engine.py`.

**Interfaces:** internal `ask`, `is_subsequence`, `allowlist_decision`, `apply_cli_rule`, `has_flag`, `is_help_call`, `is_dynamic`, `shell_command_string`, `ask_inert_flag`, `has_unsafe_flag`, `later_scan`, `eval_tokens`.

- [ ] **Step 1:** No new tests: the Bash part of the corpus legs (Task 1) and `tests/test_rule_kinds.py` drive this. Port in JS order; run `-k "py and not mcp"` after each function group.

### Task 5: MCP rules and `classify`

**Files:** Modify `lib/destructive_guard/gate_engine.py`; retarget remaining bridge parts of `tests/test_gate_engine.py`.

**Interfaces (Produces):** `classify(input: object, rules: Rules, *, strict: bool = True) -> dict | None` (`{"decision": "ask", "reason": ..., "source": ..., "commandUnparsable"?: True}` as JS); internal `tool_suffix_match`, `eval_mcp`, `tool_words`, `input_strings`, `eval_mcp_pattern`, `is_cli_rule`, `classify_inner`. Re-exports from `rules`: `RulesError`, `PACKS_DIR`, `DEFAULT_PACKS`, `pack_path`, `load_rules`, `compose_rules`, `load_packs`, `parse_rules`.

- [ ] **Step 1:** Run all corpus `_py` legs → green. Any mismatch: fix the port, never the case.
- [ ] **Step 2:** Add `test_classify_non_object_input` (Python `None`, `"x"`, list → `unparsable:`), matching the P2 hook row.

### Task 6: Verify, commit

- [ ] **Step 1:** Node suites (735 / 68), `uv run pytest`, `uv run ruff check .`; report corpus timing (`--durations=5`) and `GD_IMPL=py` failure count.
- [ ] **Step 2:** `docs/plans/python-port.md` §4: mark P5 done (link this file; note a P5a/P5b split if taken).
- [ ] **Step 3:** One commit by file name, `Python port P5: destructive_guard gate_engine`, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Do not push.

## Adjustments at execution

Done as **one commit** (no P5a/P5b split): the tokenizer is ~330 lines of the module, well under the split threshold in spirit, and the corpus legs only go green once evaluation exists.

- **Corpus leg:** no separate `tests/_corpus_py.py` (with `--import-mode=importlib` sibling test modules are not importable); `classify_case(corpus_env, case)` and `hook_input(case)` live in `tests/test_corpus.py` next to the contract leg. The `_py` tests are `test_destructive_case_py`, `test_gate_rules_case_py`, `test_gate_engine_case_py` (150 + 198 + 189 = 537 cases; the plan said ~533). The strictness comes from `read_config(env)["strict"]` (so the `destructive` corpus, whose env is `{}`, runs loose like the contract leg), not from the corpus env directly.
- **Retargets** (`tests/test_gate_engine.py`): only `test_split_command` used the bridge; it now calls `split_command` and the `raises` helper uses the real `UnparsableError`. The marker line is removed; no bridge use is left in the file. Added in-process `classify` tests (reasons, `commandUnparsable`, loose mode, non-object input `None`/`"x"`/list/int, input-level failures) and a re-export test.
- **Fixtures:** `tests/fixtures/split_command.json` (516 commands: every Bash command of the three corpora plus 40 parser edge cases, 15 of them errors) and `tests/fixtures/normalize.json` (1002 rows: `stripWrappers`, `nestedShellString`, `shellScriptIndex` for each distinct simple command, with the default packs and with `engine_rules.json`). Generated once from the JS with a throwaway node script (not committed). `normalize` itself is not exported by the JS, so it is covered through `strip_wrappers` and the corpus.
- **Module API:** `split_command(cmd, *, loose=False)`; `loose` and the JS `currentScope` are explicit parameters. Simple commands are `Cmd(list)` objects carrying `stdin` and `scope` (compare as plain lists, hash by identity because P6 keys on `scope` and `scope.host`). `Scope` has `parent` and `host`.
- All other task interfaces are as planned; helper names are the snake_case of the JS names (`scan_list`, `find_backtick_end`, `find_brace_end`, `extract_subs`, `parse_shell`, `nested_strings`, `split_inner`, `strip_options`, `split_words`, `strip_version`, `normalize`, `allowlist_decision`, `apply_cli_rule`, `later_scan`, `eval_tokens`, `eval_mcp`, `eval_mcp_pattern`, `tool_words`, `input_strings`).
