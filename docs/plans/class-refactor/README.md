# Class Refactor (one class per file) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **One task = one file in this folder.** Each task file has its own plan: what moves (with source line numbers), the call sites to switch, numbered steps, verification and the commit. **One task = one new file = one class** (a few tasks create two or three, see the table). Every task leaves `uv run pytest` and `uv run ruff check .` green. Tasks are grouped into work packages R1–R9 (44 tasks, listed under [Tasks](#tasks)); the last task of each package makes the package's single commit (repo rule: one commit per work package).

**Goal:** every function of the shipped Python code (`plugins/destructive-guard/lib/destructive_guard/`, `plugins/gated-dev-simple-workflow/scripts/gated_dev/`) lives in a class, each class in its own file. The `# ----- / # Section / # -----` banners inside today's big modules become the class boundaries (e.g. `# Shell tokenizer` in `gate_engine.py` → `ShellTokenizer` in `destructive_guard/shell/tokenizer.py`). Tests reach the code through the new classes. Behaviour is unchanged.

**Architecture:** pure move-and-wrap, bottom-up in dependency order, so each task's class only depends on classes that already exist. Each task (1) creates the class file and moves the listed functions in as methods, (2) deletes them from the old module, (3) switches every caller — production and tests — to the class. An old module is deleted by the task that empties it. No re-export shims are left at the end; the one test that asserts a re-export (`test_rules_api_is_reexported`) is deleted in Task 4.

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
- **Package/module name clash:** a package directory wins over a same-named module, so `rules/`, `check/` and `launch/` cannot exist next to `rules.py`, `check.py`, `launch.py`. The first task that creates such a package (Tasks 2, 26, 31) first does `git mv <module>.py _<module>_old.py` and points every importer at the temporary name; the task that empties it (Tasks 4, 28, 35) deletes it. This is a rename, not a shim: nothing re-exports, and it is gone by the end of the package.
- **Monkeypatch → injection:** tests that today `monkeypatch.setattr(gate_scripts, "collect_scripts", ...)` (`test_gate_fn.py`) get a constructor argument on `Gate` instead.
- Public repo hygiene as in `CLAUDE.md`. Stage files by name.
- **`testkit/` is in scope** (decided 2026-11-21) but comes last (R9), after the shipped code, so its call sites into the plugins change during R1–R8 and its own shape changes once. During R1–R8 only its calls into the plugins are edited. `conftest.py` files and `test_*.py` modules are not refactored; only their call sites change.

**Decisions confirmed (2026-11-21):** one `errors.py` per package; colliding modules are renamed out of the way first (see Package/module name clash); Tasks 35 and 37 create two files each; no re-export shims; `testkit/` refactored (R9); `find_project_root` vs `paths.project_dir` noted, not merged.

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

testkit/                         (module names stay; R9)
  envs.py                        IsolatedEnv
  projects.py                    TempProject
  pythons.py                     Pythons
  gitrepo.py                     GitRepo
  fakebin.py                     FakeBin            (existing class)
  impl.py                        Impl               (existing class)
  jev_mock.py                    JevMock            (existing class)
  hook.py                        HookRunner
  hook_result.py                 HookResult
  check_cli.py                   CheckRunner
  stubs.py                       EntryStubs
  porting.py                     PortingMap
  bench_gate.py                  GateBench          (+ main)
  _fast_sleep.py                 FastSleep
```

Removed when emptied: `gate_engine.py`, `gate_scripts.py`, `gate_jev.py`, `rules.py`, `check.py`, `gate_main.py`, `gated_dev/launch.py`, `gated_dev/watch_pr.py`.

Name changes beyond `Class.method`: `ask_inert_flag` → `Verdict.inert_flag`, `read_jev_config` → `JevConfig.read`, `collect_scripts` → `ScriptCollector.collect`, testkit `clean_env` → `IsolatedEnv.clean`, `select_impl` → `Impl.select`, `DEFAULT_IMPL` → `Impl.DEFAULT`, `run_hook` → `HookRunner.run`, `_sleep` → `FastSleep.sleep`.

Module paths for the entry stubs change: `lib/gate_main.py` → `from destructive_guard.hook import main`, `lib/check.py` → `from destructive_guard.check.cli import main`, `scripts/launch.py` → `from gated_dev.launch.cli import main`, `scripts/watch_pr.py` → `from gated_dev.watch.cli import main`. (`rules.py`, `check.py` and `launch.py` collide with the new packages; see Package/module name clash.)

---

## Tasks

Call sites and line numbers in the task files are a snapshot of commit `b807586` (generated from the code with `ast`); each task starts by re-running its `git grep`.

| Task | Package | Creates | Commit |
| --- | --- | --- | --- |
| [1](R1-01-errors-verdict.md) | R1 | `errors.py` + `Verdict` |  |
| [2](R1-02-js-regex.md) | R1 | `rules/js_regex.py` → `JsRegex` |  |
| [3](R1-03-rule-parser.md) | R1 | `rules/rule_parser.py` → `RuleParser` |  |
| [4](R1-04-rule-loader.md) | R1 | `rules/rule_loader.py` → `RuleLoader` | `Class refactor R1: rules` |
| [5](R2-05-cmd-scope.md) | R2 | `shell/cmd.py` → `Cmd`, `shell/scope.py` → `Scope` |  |
| [6](R2-06-shell-tokenizer.md) | R2 | `shell/tokenizer.py` → `ShellTokenizer` | `Class refactor R2: shell tokenizer` |
| [7](R3-07-normalizer.md) | R3 | `engine/normalizer.py` → `CommandNormalizer(rules)` |  |
| [8](R3-08-cli-rule-matcher.md) | R3 | `engine/cli_rule_matcher.py` → `CliRuleMatcher(rules)` |  |
| [9](R3-09-command-evaluator.md) | R3 | `engine/command_evaluator.py` → `CommandEvaluator(rules)` |  |
| [10](R3-10-mcp-evaluator.md) | R3 | `engine/mcp_evaluator.py` → `McpEvaluator(rules)` |  |
| [11](R3-11-classifier.md) | R3 | `engine/classifier.py` → `Classifier(rules, strict=True)` | `Class refactor R3: rule evaluation` |
| [12](R4-12-project-paths.md) | R4 | `scripts/project_paths.py` → `ProjectPaths` |  |
| [13](R4-13-run-targets.md) | R4 | `scripts/run_targets.py` → `RunTargetResolver(rules, cwd, root)` |  |
| [14](R4-14-source-follower.md) | R4 | `scripts/source_follower.py` → `SourceFollower` |  |
| [15](R4-15-script-collector.md) | R4 | `scripts/script_collector.py` → `ScriptCollector(rules, cwd, root)` |  |
| [16](R4-16-script-scanner.md) | R4 | `scripts/script_scanner.py` → `ScriptScanner(rules)` | `Class refactor R4: scripts` |
| [17](R5-17-jev-config.md) | R5 | `jev/config.py` → `JevConfig` |  |
| [18](R5-18-jev-prompt.md) | R5 | `jev/prompt.py` → `JevPrompt` |  |
| [19](R5-19-redactor.md) | R5 | `jev/redactor.py` → `Redactor` |  |
| [20](R5-20-jev-request.md) | R5 | `jev/request.py` → `JevRequest` |  |
| [21](R5-21-jev-client.md) | R5 | `jev/client.py` → `JevClient(now=..., sleep=...)` |  |
| [22](R5-22-jev-decider.md) | R5 | `jev/decider.py` → `JevDecider` | `Class refactor R5: Jev` |
| [23](R6-23-gate.md) | R6 | `gate/gate.py` → `Gate(rules, env, cwd, collect_scripts=None)` |  |
| [24](R6-24-project-dir.md) | R6 | `paths.py` → `ProjectDir` |  |
| [25](R6-25-gate-config.md) | R6 | `config.py` → `GateConfig` |  |
| [26](R6-26-gate-dry-run.md) | R6 | `check/dry_run.py` → `GateDryRun(env, cwd)` |  |
| [27](R6-27-check-report.md) | R6 | `check/report.py` → `CheckReport` |  |
| [28](R6-28-check-cli.md) | R6 | `check/cli.py` → `CheckCli` + `main` |  |
| [29](R6-29-gate-hook.md) | R6 | `hook.py` → `GateHook` + `main` | `Class refactor R6: gate, config, check, hook` |
| [30](R7-30-errors-process.md) | R7 | `errors.py`, `process.py` → `ProcessRunner`, `completed_run.py` → `CompletedRun` |  |
| [31](R7-31-launch-naming.md) | R7 | `launch/naming.py` → `LaunchNaming` |  |
| [32](R7-32-terminal.md) | R7 | `launch/terminal.py` → `TerminalCommands` |  |
| [33](R7-33-ticket-project.md) | R7 | `launch/ticket_project.py` → `TicketProject(root, run=...)` |  |
| [34](R7-34-orca.md) | R7 | `launch/orca.py` → `OrcaWorktrees(root, run=...)` |  |
| [35](R7-35-launcher-cli.md) | R7 | `launch/launcher.py` → `TicketLauncher`, `launch/cli.py` → `LaunchCli` + `main` | `Class refactor R7: launcher` |
| [36](R8-36-pr-client-feedback.md) | R8 | `watch/pr_client.py` → `PrClient(run=...)`, `watch/feedback.py` → `FeedbackDetector` |  |
| [37](R8-37-watcher-cli.md) | R8 | `watch/watcher.py` → `PrWatcher`, `watch/cli.py` → `WatchPrCli` + `main` |  |
| [38](R8-38-notifier.md) | R8 | `notify.py` → `Notifier` + `main` | `Class refactor R8: PR watcher and notify` |
| [39](R9-39-env-projects-pythons.md) | R9 | `envs.py` → `IsolatedEnv`, `projects.py` → `TempProject`, `pythons.py` → `Pythons` |  |
| [40](R9-40-gitrepo-fakebin.md) | R9 | `gitrepo.py` → `GitRepo`, `fakebin.py`: `absolute` → `FakeBin.absolute` |  |
| [41](R9-41-impl-jev-mock.md) | R9 | `impl.py`: `select_impl` → `Impl.select`, `jev_mock.py`: `probs` → `JevMock.probs` |  |
| [42](R9-42-hook-runner.md) | R9 | `hook.py` → `HookRunner`, `hook_result.py` → `HookResult` |  |
| [43](R9-43-check-stubs-porting.md) | R9 | `check_cli.py` → `CheckRunner`, `stubs.py` → `EntryStubs`, `porting.py` → `PortingMap` |  |
| [44](R9-44-bench-fast-sleep.md) | R9 | `bench_gate.py` → `GateBench` + `main`, `_fast_sleep.py` → `FastSleep` | `Class refactor R9: testkit` |
