# L2: Delete the rule gate

> Part of the [lean gate plan](README.md). Depends on: L1 (the hook no longer imports anything deleted here).

Delete:

- `lib/destructive_guard/{engine,shell,scripts,rules,gate}/`, `verdict.py`,
  `jev/decider.py`, `packs/`.
- From `errors.py`: `RulesError`, `UnparsableError`.
- From `config.py`: everything except `enabled`, `envGuard`, `log` and
  `ProjectDir` resolution; `available_packs`, `build_rules`, `_read_checks`
  go.
- From `jev/redactor.py`: `redact_script` (and `_drop_env_lines` if MCP no
  longer needs it after D9).
- From `jev/prompt.py`: `safe` becomes optional (validated if present, unused
  by the decision); the built-in prompts keep it for the log.
- Tests: `test_corpus.py`, `test_packs.py`, `test_rule_kinds.py`,
  `test_rules_loading.py`, `test_tokenizer.py`, `test_gate_engine.py`,
  `test_gate_scripts.py`, `test_gate_fn.py`, `tests/cases/`,
  `tests/fixtures/`, `tests/PORTING.md`.
- Tests trimmed to what still exists: `test_gate_hook.py` (registration,
  exact bytes, non-UTF-8 stdin), `test_gate_hook_jev.py` and `test_jev_http.py`
  (merge into one file on the new hook: request shape, retries, timeouts,
  redacted MCP payload, audit log), `test_jev_units.py` (drop scope/can-lift/
  allow-threshold/scripts cases), `test_jev_request_py.py` (drop
  `test_failures_keep_rule_result_*`, `test_can_lift_0_mcp`,
  `test_undecided_keeps_rule_result`, scripts payload), `test_config.py`
  (three variables + env guard), `test_gate_sh_lookup.py` (ask with a warning
  on plugin faults).
- Repo-level: `tests/test_porting.py` drops `DG` from `PLUGIN_DIRS` (the
  porting record goes with the code it recorded); `tests/test_testkit_contract.py`
  uses another variable than `GATE_CHECKS` in its examples;
  `tests/test_one_class_per_file.py` keeps working (check the listed dirs).
- `testkit/`: delete `legacy_gate.py` (L1 added it so the rule tests outlive the hook; its users
  `test_corpus`, `test_packs`, `test_gate_engine`, `test_config`, `test_check` go or lose those rows);
  delete `porting.py` only if `test_porting.py` no longer needs
  it for GD (it does: keep); delete `projects.py` if nothing imports it after
  the script tests are gone; `stubs.py` (its `STUBS` list now also has the
  workflow's `flow.py`) gains `session_main.py`, and `pyproject.toml`'s
  per-file ignores for `lib/{check,gate_main}.py` gain `session_main`.
- `pyproject.toml`: no path changes expected; re-run ruff.

Acceptance:

```bash
grep -rnE "GATE_CHECKS|GATE_STRICT|GATE_RULES|GATE_DISABLE_RULES|CAN_LIFT|ALLOW_THRESHOLD|JEV_SCOPE|GATE_JEV_LOG|gate-config:|unparsable:|GATE_DONE_FILE" plugins tests testkit
```

returns only `session.py`'s removed-variable list, its test and the README
migration section.

Commit: `Lean gate L2: remove rules, shell parser and script scan`.

## Done when

- [ ] `uv run pytest` and `uv run ruff check .` pass
- [ ] `claude plugin validate .` and `jq . .claude-plugin/marketplace.json` pass
- [ ] `cd plugins/destructive-guard/formal && PATH="$HOME/.elan/bin:$PATH" lake build --wfail` passes
- [ ] one commit with the message given above; nothing pushed unless asked
