# Class Refactor (one class per file) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **One task = one new file = one class.** Every task leaves `uv run pytest` and `uv run ruff check .` green. Tasks are grouped into work packages R1–R9 (44 tasks); the last task of each package makes the package's single commit (repo rule: one commit per work package).

**Goal:** every function of the shipped Python code (`plugins/destructive-guard/lib/destructive_guard/`, `plugins/gated-dev-simple-workflow/scripts/gated_dev/`) lives in a class, each class in its own file. The `# ----- / # Section / # -----` banners inside today's big modules become the class boundaries (e.g. `# Shell tokenizer` in `gate_engine.py` → `ShellTokenizer` in `destructive_guard/shell/tokenizer.py`). Tests reach the code through the new classes. Behaviour is unchanged.

**Architecture:** pure move-and-wrap, bottom-up in dependency order, so each task's class only depends on classes that already exist. Each task (1) creates the class file and moves the listed functions in as methods, (2) deletes them from the old module, (3) switches every caller — production and tests — to the class. An old module is deleted by the task that empties it. No re-export shims are left at the end.

**Tech Stack:** Python ≥ 3.14 (standard library only), pytest, ruff.

## Global Constraints

- **No behaviour change.** Test *expectations* do not change, only how tests call the code. The JSON fixtures (`tests/fixtures/split_command.json`, `normalize.json`, corpora) are not regenerated or edited. A failing fixture means the move changed behaviour → fix the move, not the fixture.
- **Shape of a class:**
  - State only for what every call already passes today: `rules`, `env`, `cwd`, `root`, `config`, and injected dependencies (`run`, `sleep`, `now`, `log`). These become constructor arguments.
  - Functions that take none of those become `@staticmethod`s (or `@classmethod`s when they call siblings). Do not invent state.
  - Module constants used by one class become class attributes; constants shared by several classes go to the lowest class that owns them and are referenced as `Owner.CONST`.
  - Private helpers keep their leading underscore as methods.
- **Exceptions** (`UnparsableError`, `RulesError`, `ConfigError`, `JevConfigError`, `UsageError`, `LaunchError`) are two-line classes: they go into one `errors.py` per package instead of a file each. Small value types (`Cmd`, `Scope`, `CompletedRun`) get their own file.
- **Entry points stay:** `lib/gate_main.py`, `lib/check.py`, `scripts/launch.py`, `scripts/watch_pr.py`, `hooks/notify.py` import `main` from a module. Each CLI class file keeps a one-line module-level `def main(...) -> int: return <Cls>(...).run(...)`. `test_entry_stubs.py` (both plugins) must pass unchanged.
- **Hook latency:** the gate runs on every Bash/MCP call. Keep today's lazy imports lazy (`gate_jev` and `gate_scripts` are imported inside `apply_jev` / `gate`, `config` inside `gate_main.main`, `redact` inside `log_decision`, `read_jev_config` inside `check`). `__init__.py` files stay empty. Run `testkit/bench_gate.py` before R2 and after R6; regression > 10 % → investigate before committing R6.
- **Monkeypatch → injection:** tests that today `monkeypatch.setattr(gate_scripts, "collect_scripts", ...)` (`test_gate_fn.py`) get a constructor argument on `Gate` instead.
- Public repo hygiene as in `CLAUDE.md`. Stage files by name.
- **`testkit/` is in scope** (decided 2026-11-21) but comes last (R9), after the shipped code, so its call sites into the plugins change during R1–R8 and its own shape changes once. During R1–R8 only its calls into the plugins are edited. `conftest.py` files and `test_*.py` modules are not refactored; only their call sites change.

**Decisions confirmed (2026-11-21):** one `errors.py` per package; Tasks 28, 35 and 37 empty the colliding module in the same task that creates the package; no re-export shims; `testkit/` refactored (R9); `find_project_root` vs `paths.project_dir` noted, not merged.

## Review Focus

- Moves are verbatim: diff each moved function body against the original (`git diff --color-moved`); the only allowed edits are `self.`/`Cls.` prefixes and parameters turned into attributes.
- No circular imports between the new subpackages (check `python -I -c "import destructive_guard.gate.gate"` from `lib/`).
- No leftover module-level functions besides the `main` wrappers (Task 38 adds a test for this).

## Target layout

```text
destructive_guard/
  errors.py                      UnparsableError, RulesError, ConfigError, JevConfigError, UsageError
  verdict.py                     Verdict            (the two duplicate ask() helpers)
  paths.py                       ProjectDir
  rules/js_regex.py              JsRegex
  rules/rule_parser.py           RuleParser
  rules/rule_loader.py           RuleLoader         (+ `Rules` type alias)
  shell/cmd.py                   Cmd
  shell/scope.py                 Scope
  shell/tokenizer.py             ShellTokenizer
  engine/normalizer.py           CommandNormalizer
  engine/cli_rule_matcher.py     CliRuleMatcher
  engine/command_evaluator.py    CommandEvaluator
  engine/mcp_evaluator.py        McpEvaluator
  engine/classifier.py           Classifier
  scripts/project_paths.py       ProjectPaths
  scripts/run_targets.py         RunTargetResolver
  scripts/source_follower.py     SourceFollower
  scripts/script_collector.py    ScriptCollector
  scripts/script_scanner.py      ScriptScanner
  jev/config.py                  JevConfig
  jev/prompt.py                  JevPrompt
  jev/redactor.py                Redactor
  jev/request.py                 JevRequest
  jev/client.py                  JevClient
  jev/decider.py                 JevDecider
  gate/gate.py                   Gate
  config.py                      GateConfig
  check/dry_run.py               GateDryRun
  check/report.py                CheckReport
  check/cli.py                   CheckCli           (+ main)
  hook.py                        GateHook           (+ main; replaces gate_main.py)

gated_dev/
  errors.py                      LaunchError
  process.py                     ProcessRunner
  completed_run.py               CompletedRun
  launch/naming.py               LaunchNaming
  launch/terminal.py             TerminalCommands
  launch/ticket_project.py       TicketProject
  launch/orca.py                 OrcaWorktrees
  launch/launcher.py             TicketLauncher
  launch/cli.py                  LaunchCli          (+ main)
  watch/pr_client.py             PrClient
  watch/feedback.py              FeedbackDetector
  watch/watcher.py               PrWatcher
  watch/cli.py                   WatchPrCli         (+ main)
  notify.py                      Notifier           (+ main)
```

Removed when emptied: `gate_engine.py`, `gate_scripts.py`, `gate_jev.py`, `rules.py`, `check.py`, `gate_main.py`, `gated_dev/launch.py`, `gated_dev/watch_pr.py`.

Module paths for the entry stubs change: `lib/gate_main.py` → `from destructive_guard.hook import main`, `lib/check.py` → `from destructive_guard.check.cli import main`, `scripts/launch.py` → `from gated_dev.launch.cli import main`, `scripts/watch_pr.py` → `from gated_dev.watch.cli import main`. (`check.py` and `launch.py` module names collide with the new packages, so the module is removed in the same task that creates the package.)

---

## R1 — destructive-guard: rules (`rules.py`)

### Task 1: `errors.py` + `Verdict`

**Files:** Create `destructive_guard/errors.py`, `destructive_guard/verdict.py`. Modify all modules defining or importing the exceptions; `gate_engine.py` and `gate_scripts.py` (`ask`).

- [ ] Move all exception classes of the plugin into `errors.py`; import them from there everywhere (tests: `test_rules_loading.py`, `test_jev_*.py`, `test_gate_engine.py`, `test_tokenizer.py`, `test_config.py`).
- [ ] `Verdict.ask(rule_id, detail)` replaces `gate_engine.ask` and `gate_scripts.ask`; also `ask_inert_flag` → `Verdict.inert_flag()`. `gate_main.py` imports `Verdict`.

### Task 2: `rules/js_regex.py` → `JsRegex`

**Moves:** `_js_str`, `_translate`, `compile_js_regex` (static).
**Tests:** callers of `compile_js_regex` in `test_rule_kinds.py`, `test_rules_loading.py`.

### Task 3: `rules/rule_parser.py` → `RuleParser`

**Moves:** `_regex`, `_str_array`, `_non_empty_str_array`, `_str_array_array`, `_flag_map`, `_bool`, `_runner_list`, `_parse_rule`, `parse_rules`.
**Tests:** `test_rules_loading.py`, `test_rule_kinds.py`.

### Task 4: `rules/rule_loader.py` → `RuleLoader` (commit R1)

**Moves:** `_Unset`, `_reject_constant`, `pack_path`, `_read_rules_json`, `load_rules`, `compose_rules`, `load_packs`, `DEFAULT_PACKS`, `PACKS_DIR`, the `Rules` alias. Delete `rules.py`.
**Callers:** `config.py`, `gate_engine.py` (it re-exports `load_rules`, `pack_path`, `DEFAULT_PACKS` today — drop the re-exports), `gate_scripts.py`.
**Tests:** `test_tokenizer.py`, `test_rules_loading.py`, `test_packs.py`, `test_rule_kinds.py`, `test_corpus.py`, `conftest.py`.
- [ ] Green → commit `Class refactor R1: rules`.

## R2 — destructive-guard: shell tokenizer (`gate_engine.py` § Shell tokenizer)

### Task 5: `shell/cmd.py` → `Cmd`, `shell/scope.py` → `Scope`

**Moves:** the two classes; `basename` becomes `Cmd.basename` (static) if only the tokenizer/evaluator use it, else `ShellTokenizer.basename`. Update `gate_scripts.py` (`from .gate_engine import Cmd as _Cmd`).

### Task 6: `shell/tokenizer.py` → `ShellTokenizer` (commit R2)

**Moves (§ Shell tokenizer, lines ~120–500):** `_REDIRECT_OP`, `_DIGITS`, `_BACKTICK_ESCAPE`, `_SIGN_START`, `_C_CLUSTER`, `_S_CLUSTER`, `_O_CLUSTER`, `MAX_DEPTH`, `DYN`, `SHELLS`, `ASSIGNMENT_RE`, `LEADING_RESERVED`; functions `scan_list`, `_scan_list`, `find_backtick_end`, `find_brace_end`, `extract_subs`, `parse_shell`, `nested_strings`, `split_inner`, `split_command`. Stateless → class/static methods; `split_command` is the public entry.
**Callers:** rest of `gate_engine.py`, `gate_scripts.py`.
**Tests:** `test_tokenizer.py` (`split_command`, `DYN`, `UnparsableError`), `test_gate_engine.py`.
- [ ] Bench baseline recorded in the commit message. Green → commit `Class refactor R2: shell tokenizer`.

## R3 — destructive-guard: evaluation (`gate_engine.py` § Normalization and rule evaluation)

### Task 7: `engine/normalizer.py` → `CommandNormalizer(rules)`

**Moves:** `WRAPPER_VALUE_OPTS`, `_VERSIONED`, `_DOLLAR_EXPANSION`, `strip_options`, `split_words`, `strip_version`, `strip_wrappers`, `shell_script_index`, `nested_shell_string`, `normalize`.
**Tests:** `test_tokenizer.py` (`strip_wrappers`, `nested_shell_string`, `shell_script_index` against `normalize.json`).

### Task 8: `engine/cli_rule_matcher.py` → `CliRuleMatcher`

**Moves:** `is_subsequence`, `allowlist_decision`, `apply_cli_rule`, `_SHORT_FLAG`, `_FLAG_BUNDLE`, `has_flag`, `is_help_call`, `is_dynamic`, `has_unsafe_flag` (the last one takes `rules` → instance with `rules`).
**Tests:** `test_gate_engine.py`, `test_rule_kinds.py`.

### Task 9: `engine/command_evaluator.py` → `CommandEvaluator(rules)`

**Moves:** `shell_command_string`, `later_scan`, `eval_tokens` (recursive; composes `ShellTokenizer`, `CommandNormalizer`, `CliRuleMatcher`).

### Task 10: `engine/mcp_evaluator.py` → `McpEvaluator(rules)`

**Moves:** `eval_mcp`, `tool_words`, `input_strings`, `eval_mcp_pattern`.

### Task 11: `engine/classifier.py` → `Classifier(rules, strict=True)` (commit R3)

**Moves:** `is_cli_rule`, `_member`, `classify`, `_classify_inner`. `gate_engine.py` now holds only `_closed`, `apply_jev`, `gate`.
**Tests:** `test_gate_engine.py`, `test_corpus.py`, `test_rule_kinds.py`, `test_packs.py`.
- [ ] Green → commit `Class refactor R3: rule evaluation`.

## R4 — destructive-guard: scripts (`gate_scripts.py`)

### Task 12: `scripts/project_paths.py` → `ProjectPaths`

**Moves (§ Project root and paths):** `_basename`, `_join`, `_resolve`, `_at`, `real_or_self`, `find_project_root`, `inside`, `rel_path`, `glob_to_regexp`, `is_exempt_path`.
- [ ] Compare `find_project_root(cwd, env)` with `paths.project_dir(env, cwd)`; if they compute the same thing, note it in the commit message as a follow-up — **do not merge** in this refactor (behaviour freeze).

### Task 13: `scripts/run_targets.py` → `RunTargetResolver(rules, cwd, root)`

**Moves (§ Which project files does a command run?):** `unresolvable`, `leading_options`, `node_operands`, `python_operand`, `first_operand`, `read_scripts`, `workflow_name`, `resolve_workflow`, `option_value`, `terraform_test_targets`, `run_targets`, `expand_vars`, `_copy_state`, `command_targets`.

### Task 14: `scripts/source_follower.py` → `SourceFollower`

**Moves (§ Following source and imports):** `source_targets`, `is_file`, `resolve_import`, `import_targets`, `kind_of`, `read_head` and their regex constants.

### Task 15: `scripts/script_collector.py` → `ScriptCollector(rules, cwd, root)`

**Moves:** `collect_scripts`.

### Task 16: `scripts/script_scanner.py` → `ScriptScanner(rules)` (commit R4)

**Moves (§ Scan):** `escape_re`, `program_names`, `scan_scripts` (`ask` already in `Verdict`). Delete `gate_scripts.py`.
**Tests:** `test_gate_scripts.py` (682 lines; mostly call-site edits), `test_gate_fn.py` (temporarily patch `ScriptCollector.collect` until Task 23 adds injection).
- [ ] `tests/test_no_js.py` allowlist: replace `gate_scripts.py` with `scripts/*.py` (recognition logic moved).
- [ ] Green → commit `Class refactor R4: scripts`.

## R5 — destructive-guard: Jev (`gate_jev.py`)

### Task 17: `jev/config.py` → `JevConfig`

**Moves (§ Configuration):** `_optional`, `_scope`, `_can_lift`, `_probability`, `_check_url`, `read_jev_config` (→ `JevConfig.read(env, cwd=...)`, still returns the same dict or `None`).

### Task 18: `jev/prompt.py` → `JevPrompt`

**Moves (§ Prompt):** `validate_prompt`, `_read_prompt_file`, `builtin_prompt`, `prompt_from_env`. **Tests:** `test_jev_prompt.py`.

### Task 19: `jev/redactor.py` → `Redactor`

**Moves (§ Redaction):** its regex constants, `references_env_file`, `_looks_encoded`, `_redact_text`, `redact`, `_drop_env_lines`, `redact_script`, `_redact_sql_literals`, `_redact_mcp_value`, `redact_mcp_input`. Lazy import in `gate_main.log_decision` now points here.

### Task 20: `jev/request.py` → `JevRequest`

**Moves (§ State and answer):** `_dumps`, `_prompt_of`, `request_body`, `_byte_length`, `scripts_payload`, `problem_notes`, `build_state`, `_get`, `parse_answer`. **Tests:** `test_jev_request_py.py`.

### Task 21: `jev/client.py` → `JevClient(now=..., sleep=...)`

**Moves (§ Jev request):** `retry_delay`, `_is_timeout`, `ask_jev`. **Tests:** `test_jev_http.py`.

### Task 22: `jev/decider.py` → `JevDecider` (commit R5)

**Moves (§ Decision):** `_fmt`, `_top_of`, `jev_decision`, `audit`, `run_jev`. Delete `gate_jev.py`; the lazy `from . import gate_jev` in `apply_jev` becomes a lazy `from .jev.decider import JevDecider`.
**Tests:** `test_jev_units.py`, `test_gate_hook_jev.py` (subprocess — should need no edit).
- [ ] Green → commit `Class refactor R5: Jev`.

## R6 — destructive-guard: gate, config, check, hook

### Task 23: `gate/gate.py` → `Gate(rules, env, cwd, collect_scripts=None)`

**Moves:** `_closed`, `apply_jev`, `gate`. Delete `gate_engine.py`. `collect_scripts` injectable (default: lazy `ScriptCollector`). **Tests:** `test_gate_fn.py` uses the constructor argument instead of `monkeypatch`. `tests/test_no_js.py` allowlist: `gate_engine.py` → `shell/*.py`, `engine/*.py`.

### Task 24: `paths.py` → `ProjectDir`

**Moves:** `project_dir`, `project_path`. **Tests:** `test_paths.py`.

### Task 25: `config.py` → `GateConfig`

**Moves:** `_TRUE`, `_FALSE`, `DEFAULT_CHECKS`, `_value`, `_flag`, `_list`, `available_packs`, `_read_checks`, `read_config`, `build_rules`. **Tests:** `test_config.py` (429 lines).

### Task 26: `check/dry_run.py` → `GateDryRun(env, cwd)`

**Moves (from `check.py`):** `JEV_VARS`, `_reject_constant`, `_num`, `_jev_summary`, `effective_config`, `_answer`, `check_call`.

### Task 27: `check/report.py` → `CheckReport`

**Moves:** `_js`, `_compact`, `format_check`, `format_config`, `_dump`.

### Task 28: `check/cli.py` → `CheckCli` + `main`

**Moves:** `parse_args`, `render`, `run`, `main`. Delete `check.py`; update `lib/check.py` stub. **Tests:** `test_check.py`, `test_entry_stubs.py`.

### Task 29: `hook.py` → `GateHook` + `main` (commit R6)

**Moves (from `gate_main.py`):** `_reject_constant`, `emit`, `log_decision`, `main`. Delete `gate_main.py`; update `lib/gate_main.py` stub.
- [ ] Docs: `plugins/destructive-guard/README.md` file table (lines ~290–294), `CLAUDE.md` § destructive-guard module paths.
- [ ] Bench vs. R2 baseline (Global Constraints).
- [ ] Bump `destructive-guard` patch version in `plugin.json` + catalog, bump `metadata.version`; `claude plugin validate .`.
- [ ] Green → commit `Class refactor R6: gate, config, check, hook`.

## R7 — gated-dev-simple-workflow: launcher (`gated_dev/launch.py`)

### Task 30: `errors.py`, `process.py` → `ProcessRunner`, `completed_run.py` → `CompletedRun`

**Moves:** `LaunchError`; `CompletedRun`; `default_run`, `_terminal_handle` (`launch.py`). `watch_pr.default_run` has another signature → stays with `PrClient` (Task 36).

### Task 31: `launch/naming.py` → `LaunchNaming`

**Moves:** `_json`, `_js_string`, `_get`, `_first`, `_SAFE_KEY`, `_SAFE_REF`, `_PLAIN_ARG`, `MAX_SHORT`, `shell_quote`, `apple_script_string`, `is_safe_key`, `short_summary`, `session_name`, `slugify`.

### Task 32: `launch/terminal.py` → `TerminalCommands`

**Moves:** `detect_host`, `iterm_session_id`, `build_shell_command`, `build_apple_script`, `build_orca_args`.

### Task 33: `launch/ticket_project.py` → `TicketProject(root, run=...)`

**Moves (§ Process and file helpers):** `DEFAULT_KEY_PATTERN`, `CONFIG_KEYS`, `_FRONT_MATTER`, `find_root`, `_outside_repo`, `read_config`, `check_key`, `read_ticket`, `list_ticket_keys`, `find_run`, `resolve_base`.

### Task 34: `launch/orca.py` → `OrcaWorktrees(root, run=...)`

**Moves:** `orca_has_repo`, `orca_worktree_args`, `create_orca_worktree`.

### Task 35: `launch/launcher.py` → `TicketLauncher`, `launch/cli.py` → `LaunchCli` + `main` (commit R7)

Two files, one task, because both empty `launch.py` and the package name collides with the module. **Moves:** `launch_tab`, `launch_ticket` → `TicketLauncher`; `USAGE`, `ALLOWED_ARGS`, `parse_args`, `describe`, `_write`, `main` → `LaunchCli`. Delete `gated_dev/launch.py`; update `scripts/launch.py` stub.
**Tests:** `test_launch_units.py` (`L.*` → classes), `test_launch_cli.py`, `test_entry_stubs.py`.
- [ ] Green → commit `Class refactor R7: launcher`.

## R8 — gated-dev-simple-workflow: PR watcher and notify

### Task 36: `watch/pr_client.py` → `PrClient(run=...)`, `watch/feedback.py` → `FeedbackDetector`

**Moves:** `default_run`, `_PR_URL`, `parse_pr_url`, `_author`, `normalize_pr`, `fetch_pr` → `PrClient`; `_iso`, `_time`, `newest_feedback_at`, `new_feedback_at` → `FeedbackDetector`.

### Task 37: `watch/watcher.py` → `PrWatcher`, `watch/cli.py` → `WatchPrCli` + `main`

**Moves:** `POLL_MS`, `MAX_GH_FAILURES`, `MARKER`, `_default_sleep`, `_default_log`, `_read_state`, `_write_heartbeat`, `watch` → `PrWatcher`; `EXIT`, `_parse_args`, `main` → `WatchPrCli`. `main(**deps)` keeps accepting the same injected dependencies. Delete `gated_dev/watch_pr.py`; update `scripts/watch_pr.py` stub.
**Tests:** `test_watch_pr_units.py` (`wp.*`), `test_watch_pr.py`, `test_entry_stubs.py`.

### Task 38: `notify.py` → `Notifier` + `main` (commit R8)

**Moves:** `DEFAULT_MESSAGE`, `_OSASCRIPT`, `_message`, `_os_name`, `_run`, `_notify`; `main` stays a wrapper. **Tests:** `test_notify.py`.
- [ ] Guard test `tests/test_one_class_per_file.py`: for every `.py` under the two shipped packages, `ast`-parse and assert at most one non-exception class per file and no module-level `def` other than `main` (`errors.py` exempt).
- [ ] Docs: `CLAUDE.md` § gated-dev-simple-workflow paths; `skills/ticket/SKILL.md` / references if they name `gated_dev/*.py`.
- [ ] Bump `gated-dev-simple-workflow` patch version (plugin.json + catalog), bump `metadata.version`; `claude plugin validate .`.
- [ ] Green → commit `Class refactor R8: PR watcher and notify`.

## R9 — testkit (`testkit/`, not shipped)

Module names stay (the class goes into the existing file) so the `from testkit.<module> import ...` paths only change their imported name. `testkit/__init__.py` keeps its path constants (`REPO`, `PLUGINS`, `DG`, `GD`); it has no functions. No version bump (not shipped). Callers: `conftest.py`, `plugins/*/tests/*.py`, `tests/test_testkit_*.py`, `tests/test_porting.py`.

### Task 39: `envs.py` → `TestEnv`, `projects.py` → `TempProject`, `pythons.py` → `Pythons`

**Moves:** `clean_env` → `TestEnv.clean`; `temp_project`, `provision_project` → `TempProject` (static); `find_python`, `_version`, `require_new_python`, `_is_old`, `find_old_python` → `Pythons` (static/class methods). Three small leaf modules, one task: every other testkit module depends on them.
**Tests:** `tests/test_testkit_contract.py`, `tests/test_testkit_impl.py`, every plugin test that imports them (see `grep -rn "from testkit"`).

### Task 40: `gitrepo.py` → `GitRepo`, `fakebin.py` (`absolute` → `FakeBin.absolute`)

**Moves:** `git_env`, `git`, `init_repo`, `add_worktree` → `GitRepo` (static); `absolute` → `FakeBin.absolute` (static). **Tests:** `tests/test_testkit_fakebin.py`, `test_launch_cli.py`, `test_watch_pr.py`, `test_notify.py`, `test_run_python.py`, `test_gate_sh_lookup.py`.

### Task 41: `impl.py` (`select_impl` → `Impl.select`), `jev_mock.py` (`probs` → `JevMock.probs`)

**Moves:** `DEFAULT_IMPL` → `Impl.DEFAULT`; `select_impl` → `Impl.select` (classmethod); `probs` → `JevMock.probs` (static). **Tests:** `conftest.py` (root), `tests/test_testkit_impl.py`, `test_jev_*.py`, `test_gate_hook_jev.py`, `test_corpus.py`, `test_watch_pr.py`.

### Task 42: `hook.py` → `HookRunner`, `hook_result.py` → `HookResult`

**Moves:** `ASK_TEMPLATE`, `bash_input`, `mcp_input`, `run_hook`, `decision` → `HookRunner` (static; `run` takes `impl` like today). `HookResult` dataclass to its own file. **Tests:** `test_gate_hook.py`, `test_gate_hook_jev.py`, `test_gate_engine.py`, `test_corpus.py`, `test_packs.py`, `test_check.py`, `test_config.py`, `test_jev_http.py`, `test_gate_sh_lookup.py`.

### Task 43: `check_cli.py` → `CheckRunner`, `stubs.py` → `EntryStubs`, `porting.py` → `PortingMap`

**Moves:** `run_check`, `check_call` → `CheckRunner` (named so it does not read like the shipped `CheckCli`); `stubs_of`, `stub_id`, `check_parses_as_37`, `check_old_python_exit_3`, `check_314_imports_package` → `EntryStubs`; `js_tests`, `_split_row`, `read_map`, `escape_cell` → `PortingMap`. **Tests:** `test_check.py`, `test_corpus.py`, `test_rule_kinds.py`, `test_gate_engine.py`, `test_jev_prompt.py`, `test_config.py`, `test_watch_pr.py`, both `test_entry_stubs.py`, `tests/test_porting.py`.
- [ ] Note in the commit message: `PortingMap.js_tests` returns `[]` everywhere since P14 (no JS left); deleting `porting.py` + `test_porting.py` is a follow-up, not part of this refactor.

### Task 44: scripts `bench_gate.py` → `GateBench` + `main`, `_fast_sleep.py` → `FastSleep` (commit R9)

**Moves:** `inputs`, `pct`, `main` → `GateBench`; module-level `main()` wrapper stays so `python -m testkit.bench_gate` works. `_sleep` → `FastSleep.sleep` (static); the top-level patch-and-run code goes into `FastSleep.run(argv)` called under `if __name__ == "__main__":` — `python -I _fast_sleep.py <script>` keeps working (`impl.py` invokes it by path; `tests/test_testkit_impl.py` asserts the path).
- [ ] Extend `tests/test_one_class_per_file.py` (Task 38) to `testkit/`: `__init__.py` exempt; `main` allowed in `bench_gate.py`.
- [ ] Run `uv run python -m testkit.bench_gate --n 50` once (smoke).
- [ ] Green → commit `Class refactor R9: testkit`.
