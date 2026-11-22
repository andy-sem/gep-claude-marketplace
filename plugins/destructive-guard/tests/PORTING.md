# Porting map: destructive-guard

One row per JS test (`test/*.test.mjs`). The last column says where the Python
port lives: `todo`, `dropped: <reason>`, or `<path relative to the plugin>::<test_name>`
(several targets separated by `, `). `tests/test_porting.py` checks that every JS
test has a row and that every target exists.

| JS file | JS test | Python test |
| --- | --- | --- |
| check.test.mjs | parseArgs: command, MCP call, config and options | tests/test_check.py::test_parse_args_command_mcp_config_and_options |
| check.test.mjs | run: usage errors exit 2 | tests/test_check.py::test_usage_errors_exit_2 |
| check.test.mjs | checkCall with default packs: sample commands | tests/test_check.py::test_check_call_default_packs |
| check.test.mjs | checkCall honours GATE_DISABLE_RULES, GATE_ENABLED and GATE_CHECKS | tests/test_check.py::test_check_call_honours_disable_enabled_and_checks |
| check.test.mjs | checkCall reports config errors as gate-config asks | tests/test_check.py::test_check_call_config_errors_ask_gate_config |
| check.test.mjs | checkCall never contacts Jev without --jev, and says when it would | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| check.test.mjs | effectiveConfig: defaults, rule ids, Jev redaction, errors | tests/test_check.py::test_effective_config_defaults_ids_redaction_errors |
| check.test.mjs | CLI: text and JSON output, key never printed | tests/test_check.py::test_cli_text_and_json_output_key_never_printed |
| check.test.mjs | the skill's documented invocations pass the gate themselves | tests/test_check.py::test_documented_invocations_pass_the_gate |
| check.test.mjs | --cwd resolves scripts the command runs | tests/test_check.py::test_cwd_resolves_scripts_the_command_runs |
| check.test.mjs | checkCall: a relative GATE_RULES_FILE resolves against the git root of --cwd | tests/test_check.py::test_relative_rules_file_resolves_against_git_root_of_cwd |
| config.test.mjs | defaults: enabled, base + destructive, env guard on, not strict, no log | tests/test_config.py::test_read_config_defaults |
| config.test.mjs | boolean variables accept 0/1/true/false/yes/no/on/off and reject the rest | tests/test_config.py::test_boolean_variables |
| config.test.mjs | GATE_CHECKS selects packs; base is always first and not duplicated | tests/test_config.py::test_gate_checks_selects_packs |
| config.test.mjs | GATE_CHECKS: unknown pack, none mixed with packs, none without a file -> ConfigError | tests/test_config.py::test_gate_checks_errors |
| config.test.mjs | GATE_CHECKS=none + GATE_RULES_FILE is a full replacement | tests/test_config.py::test_gate_checks_none_with_file_replaces |
| config.test.mjs | GATE_RULES_FILE is appended after the default packs | tests/test_config.py::test_gate_rules_file_appended_after_default_packs |
| config.test.mjs | GATE_RULES (deprecated) replaces the packs and cannot be mixed | tests/test_config.py::test_gate_rules_deprecated_replaces_packs |
| config.test.mjs | GATE_DISABLE_RULES and GATE_LOG are read as given | tests/test_config.py::test_disable_rules_and_log_read_as_given |
| config.test.mjs | relative paths resolve against CLAUDE_PROJECT_DIR; absolute paths are kept | tests/test_config.py::test_relative_paths_resolve_against_project_dir |
| config.test.mjs | without CLAUDE_PROJECT_DIR relative paths resolve against the git root of cwd, else cwd | tests/test_config.py::test_relative_paths_resolve_against_git_root_else_cwd |
| config.test.mjs | availablePacks lists the shipped packs | tests/test_config.py::test_available_packs_lists_shipped_packs |
| config.test.mjs | buildRules: default packs ask on destructive commands only | tests/test_config.py::test_build_rules_default_packs |
| config.test.mjs | buildRules: optional packs and an extra rules file add rules | tests/test_config.py::test_build_rules_optional_packs_and_extra_file |
| config.test.mjs | buildRules: GATE_CHECKS=none + file loads only the file | tests/test_config.py::test_build_rules_checks_none_loads_only_file |
| config.test.mjs | buildRules: GATE_DISABLE_RULES drops rules; unknown ids are an error | tests/test_config.py::test_build_rules_disable_rules |
| config.test.mjs | buildRules: a missing or broken rules file is a RulesError | tests/test_config.py::test_build_rules_missing_or_broken_file |
| config.test.mjs | strict: parser-uncertainty asks; loose: no opinion, other parts still checked | tests/test_config.py::test_strict_asks_loose_still_checks_other_parts |
| config.test.mjs | hook: defaults ask on destructive, pass the rest | tests/test_config.py::test_hook_defaults |
| config.test.mjs | hook: GATE_ENABLED=0 emits nothing, even for invalid input or config | tests/test_config.py::test_hook_disabled_emits_nothing |
| config.test.mjs | hook: bad configuration fails closed with gate-config | tests/test_config.py::test_hook_bad_configuration_fails_closed |
| config.test.mjs | hook: pack selection, extra file and disabled rules | tests/test_config.py::test_hook_pack_selection_extra_file_disabled_rules |
| config.test.mjs | hook: a relative GATE_RULES_FILE works after the session cd'ed into a subdirectory | tests/test_config.py::test_hook_relative_rules_file_from_subdirectory |
| config.test.mjs | hook: GATE_LOG appends one redacted JSON line per decision | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| config.test.mjs | hook: GATE_LOG is not written when the gate is off, and a bad path never breaks the gate | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| config.test.mjs | env guard matches env file names only | tests/test_config.py::test_env_guard_matches_env_file_names_only |
| config.test.mjs | env guard is off with GATE_ENV_GUARD=0 or GATE_ENABLED=0, on for other values | tests/test_config.py::test_env_guard_switches |
| destructive.test.mjs | destructive: ${label} -> ${expected} | tests/test_corpus.py::test_destructive_case |
| destructive.test.mjs | every destructive rule has at least one asking case | tests/test_corpus.py::test_every_destructive_rule_has_an_asking_case |
| destructive.test.mjs | destructive rules do not make the script scan ask | tests/test_corpus.py::test_destructive_rules_do_not_make_script_scan_ask |
| destructive.test.mjs | whenFlags: every group needs one flag; bundles only with shortBundles | tests/test_rule_kinds.py::test_when_flags_groups_and_short_bundles |
| destructive.test.mjs | unlessFlags keep exact matching without shortBundles | tests/test_rule_kinds.py::test_unless_flags_exact_without_short_bundles |
| destructive.test.mjs | dynamicArgs: ask (default) vs ignore | tests/test_rule_kinds.py::test_dynamic_args_ask_vs_ignore |
| destructive.test.mjs | whenArgs honours ignoreCase and matchStdin | tests/test_rule_kinds.py::test_when_args_ignore_case_and_match_stdin |
| destructive.test.mjs | new rule fields are validated | tests/test_rule_kinds.py::test_new_rule_fields_are_validated |
| destructive.test.mjs | mcp-pattern: tool regex alone, words split on camelCase | tests/test_rule_kinds.py::test_mcp_pattern_tool_regex_and_camel_case_words |
| env-guard.test.mjs | env guard blocks .env files for Read, Edit and Write | tests/test_env_guard.py::test_blocks_env_files |
| env-guard.test.mjs | env guard allows .env.example and ordinary files | tests/test_env_guard.py::test_allows_example_and_ordinary_files |
| env-guard.test.mjs | env guard works without jq | tests/test_env_guard.py::test_works_without_jq |
| gate-engine.test.mjs | classify: ${label} -> ${expected} | tests/test_corpus.py::test_gate_engine_case |
| gate-engine.test.mjs | allowlist reasons name the write verb | tests/test_gate_engine.py::test_allowlist_reasons_name_the_write_verb |
| gate-engine.test.mjs | dynamic arguments name the reason | tests/test_gate_engine.py::test_dynamic_arguments_name_the_reason |
| gate-engine.test.mjs | loadRules accepts legacy and object runners and rejects bad ones | tests/test_gate_engine.py::test_load_rules_runners |
| gate-engine.test.mjs | shell reading stdin is unparsable, with a reason | tests/test_gate_engine.py::test_shell_reading_stdin_reason |
| gate-engine.test.mjs | non-object input fails closed | tests/test_gate_engine.py::test_non_object_input_fails_closed |
| gate-engine.test.mjs | splitCommand returns one token list per simple command | tests/test_gate_engine.py::test_split_command |
| gate-engine.test.mjs | loadRules throws RulesError on bad config | tests/test_gate_engine.py::test_load_rules_bad_config |
| gate-engine.test.mjs | loadRules ignores a leftover protectedBranches and rejects removed kinds | tests/test_gate_engine.py::test_load_rules_legacy_and_removed_kinds |
| gate-engine.test.mjs | loadRules fails closed on a malformed inertUnsafeFlags | tests/test_gate_engine.py::test_load_rules_inert_unsafe_flags |
| gate-engine.test.mjs | CLI: emits ask for a gated command and exits 0 | tests/test_gate_engine.py::test_cli_gated_command_asks |
| gate-engine.test.mjs | CLI: prints nothing for a non-gated command | tests/test_gate_engine.py::test_cli_non_gated_prints_nothing |
| gate-engine.test.mjs | CLI: subagent calls (agent_id) still get ask | tests/test_gate_engine.py::test_cli_subagent_call_still_asks |
| gate-engine.test.mjs | CLI: broken rules file asks with gate-config for every call | tests/test_gate_engine.py::test_cli_broken_rules_asks_gate_config |
| gate-engine.test.mjs | CLI: unparsable stdin asks (fails closed) | tests/test_gate_engine.py::test_cli_unparsable_stdin_asks |
| gate-hook.test.mjs | gated command -> ask | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | git status -> empty stdout, exit 0 | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | non-JSON stdin -> ask unparsable | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | invalid rules file -> ask gate-config | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | node unavailable -> ask | tests/test_gate_hook.py::test_interpreter_unavailable_asks |
| gate-hook.test.mjs | engine exits non-zero after partial JSON -> fixed ask only | tests/test_gate_hook.py::test_engine_partial_json_then_nonzero_gives_fixed_ask |
| gate-hook.test.mjs | engine exits 0 with empty stdout but did not run -> ask | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | empty stdin -> ask | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | script scan: a script that runs terraform asks with script: | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | script scan: a provision script that imports a cloudctl module asks with script: | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | script scan: a Cloudflare-only script passes | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | terraform rule: apply, destroy and import ask with terraform: | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | fallback passes: terraform plan/fmt/validate, --help, tests and git push | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | GATE_JEV unset -> rules-only output | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: rule-matched command classified read_only 0.97 -> empty output | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: in-scope command no rule matched, risk 0.55 -> ask | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: a command outside every rule's programs goes to Jev and its risk asks | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: read_only 0.90 -> rule result stands | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: unparsable command classified read_only 0.97 -> empty output | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: unparsable command classified risky -> jev ask | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: unsure or unreachable on unparsable command -> unparsable ask (GATE_STRICT=1) | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: unparsable command without Jev asks with GATE_STRICT=1 | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: unparsable command by default (GATE_STRICT unset) -> no opinion | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: input-level unparsable and gate-config results still ask | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: missing TYPESAFE_API_KEY -> ask gate-config | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: unreachable service -> rule result stands | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | the gate hook stays registered for Bash and every MCP tool only | tests/test_gate_hook.py::test_hook_registered_for_bash_and_mcp_only |
| gate-hook.test.mjs | jev: every Bash and MCP call makes exactly one request; file tools make none | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: risk above 0.5 asks for Bash and MCP calls no rule matched | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: unrelated 0.97 gives no output | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: read_only 0.97 lifts rule asks and script asks | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: GATE_JEV_SCOPE limits which calls are sent | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: GATE_JEV_CAN_LIFT=0 keeps rule asks, Jev still adds asks | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: invalid GATE_JEV_SCOPE or GATE_JEV_CAN_LIFT asks gate-config | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: the request for a script carries the redacted script | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: terraform test sends its test files and Jev can lift the terraform ask | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: files the gate could not read reach Jev as notes | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: imports are followed to depth 3, with per-file and total caps | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: a provision script is sent with its imports | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: MCP calls send the tool name and the redacted input | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev failures give the rule result for Bash and MCP calls | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev: an MCP call without its args and a gate-config result never reach Jev | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-hook.test.mjs | jev audit log: records carry tool, usage and latencyMs | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | redact returns null for commands referencing .env files | tests/test_jev_units.py::test_redact_returns_null_for_env_file_references |
| gate-jev.test.mjs | redact strips URL credentials | tests/test_jev_units.py::test_redact_strips_url_credentials |
| gate-jev.test.mjs | redact strips Bearer, Basic and Token values | tests/test_jev_units.py::test_redact_strips_bearer_basic_token_values |
| gate-jev.test.mjs | redact strips secret-named NAME=value and NAME: value | tests/test_jev_units.py::test_redact_strips_secret_named_assignments |
| gate-jev.test.mjs | redact strips --password style flag values | tests/test_jev_units.py::test_redact_strips_password_flag_values |
| gate-jev.test.mjs | redact strips environment assignments | tests/test_jev_units.py::test_redact_strips_environment_assignments |
| gate-jev.test.mjs | redact strips long hex runs | tests/test_jev_units.py::test_redact_strips_long_hex_runs |
| gate-jev.test.mjs | redact strips long mixed-case base64 runs | tests/test_jev_units.py::test_redact_strips_long_mixed_case_base64_runs |
| gate-jev.test.mjs | redact leaves ordinary commands unchanged | tests/test_jev_units.py::test_redact_leaves_ordinary_commands_unchanged |
| gate-jev.test.mjs | readJevConfig returns null when GATE_JEV is off | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | readJevConfig applies defaults | tests/test_jev_units.py::test_read_jev_config_defaults |
| gate-jev.test.mjs | readJevConfig reads GATE_JEV_SCOPE and GATE_JEV_CAN_LIFT | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | readJevConfig treats empty optional vars as unset | tests/test_jev_units.py::test_read_jev_config_empty_optional_vars_are_unset |
| gate-jev.test.mjs | readJevConfig reads overrides | tests/test_jev_units.py::test_read_jev_config_overrides |
| gate-jev.test.mjs | readJevConfig throws JevConfigError on invalid input | tests/test_jev_units.py::test_read_jev_config_rejects_invalid_input |
| gate-jev.test.mjs | readJevConfig accepts loopback http URLs | tests/test_jev_units.py::test_read_jev_config_accepts_loopback_http_urls |
| gate-jev.test.mjs | jevDecision passes confident read_only and unrelated | tests/test_jev_units.py::test_jev_decision_passes_confident_read_only_and_unrelated |
| gate-jev.test.mjs | jevDecision sums unrelated and read_only for the safe side | tests/test_jev_units.py::test_jev_decision_sums_unrelated_and_read_only |
| gate-jev.test.mjs | jevDecision returns null when the safe side is below the threshold | tests/test_jev_units.py::test_jev_decision_null_below_allow_threshold |
| gate-jev.test.mjs | jevDecision asks when risk exceeds the escalate threshold | tests/test_jev_units.py::test_jev_decision_asks_above_escalate_threshold |
| gate-jev.test.mjs | jevDecision does not ask at exactly the escalate threshold | tests/test_jev_units.py::test_jev_decision_no_ask_at_exactly_escalate_threshold |
| gate-jev.test.mjs | jevDecision names cloud_or_data_change when it is larger | tests/test_jev_units.py::test_jev_decision_names_cloud_or_data_change_when_larger |
| gate-jev.test.mjs | parseAnswer accepts a well-formed answer | tests/test_jev_units.py::test_parse_answer_accepts_well_formed_answer |
| gate-jev.test.mjs | parseAnswer returns null for malformed shapes | tests/test_jev_units.py::test_parse_answer_null_for_malformed_shapes |
| gate-jev.test.mjs | askJev returns probabilities, usage and latency and sends a well-formed request | tests/test_jev_http.py::test_request_shape |
| gate-jev.test.mjs | askJev has a latency on errors too | tests/test_jev_http.py::test_error_has_latency |
| gate-jev.test.mjs | askJev reports usage null when Jev sends none | tests/test_jev_http.py::test_usage_null_when_absent |
| gate-jev.test.mjs | askJev reports non-retryable http errors | tests/test_jev_http.py::test_non_retryable_http_error |
| gate-jev.test.mjs | askJev retries 429 and then succeeds | tests/test_jev_http.py::test_retries_429_then_succeeds |
| gate-jev.test.mjs | askJev gives up when retry-after exceeds the budget | tests/test_jev_http.py::test_retry_after_over_budget_gives_up |
| gate-jev.test.mjs | askJev times out when fetch hangs until aborted | tests/test_jev_http.py::test_hang_times_out |
| gate-jev.test.mjs | askJev reports network failures | tests/test_jev_http.py::test_network_failure |
| gate-jev.test.mjs | askJev reports malformed bodies | tests/test_jev_http.py::test_malformed_bodies |
| gate-jev.test.mjs | runJev returns the rule result unchanged when Jev fails | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | runJev with canLift false keeps rule asks but still adds asks | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | runJev falls back to the rule result for every failure mode | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | runJev never sends Bash commands that reference .env | tests/test_jev_http.py::test_env_reference_never_sent |
| gate-jev.test.mjs | runJev lifts a rule ask when Jev passes, for Bash and MCP | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | runJev asks even when the rules had no opinion | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | runJev keeps the rule result when Jev is undecided | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | runJev sends the Bash payload with scripts and notes | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | buildState caps the command and notes the cut | tests/test_jev_units.py::test_build_state_caps_command_and_notes_cut |
| gate-jev.test.mjs | buildState caps scripts at 64 KB in total and notes it | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | buildState notes a file cut at the per-file cap | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | runJev sends the MCP payload with a cut note | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-jev.test.mjs | redactScript removes .env lines, redacts secrets and keeps the call | tests/test_jev_units.py::test_redact_script_removes_env_lines_and_redacts_secrets |
| gate-jev.test.mjs | redactMcpInput redacts SQL literals but keeps the statement and plain ids | tests/test_jev_units.py::test_redact_mcp_input_redacts_sql_literals_keeps_statement_and_ids |
| gate-jev.test.mjs | redactMcpInput replaces dollar-quoted bodies | tests/test_jev_units.py::test_redact_mcp_input_replaces_dollar_quoted_bodies |
| gate-jev.test.mjs | redactMcpInput redacts secret keys, Bearer values and .env mentions in nested JSON | tests/test_jev_units.py::test_redact_mcp_input_redacts_nested_secrets_bearer_and_env_mentions |
| gate-jev.test.mjs | redactMcpInput handles an empty input | tests/test_jev_units.py::test_redact_mcp_input_handles_empty_input |
| gate-jev.test.mjs | runJev writes a redacted JSONL audit log with tool, usage and latency | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| gate-rules.test.mjs | loadRules accepts the shipped rule file | tests/test_corpus.py::test_shipped_rule_file_loads |
| gate-rules.test.mjs | wrangler, pulumi, cf-apply scripts and git push are not gated | tests/test_corpus.py::test_gate_rules_case |
| gate-rules.test.mjs | ${label} -> ${expected} | tests/test_corpus.py::test_gate_rules_case |
| gate-scripts.test.mjs | findProjectRoot finds the .git ancestor, falling back to the env and the cwd | tests/test_gate_scripts.py::test_find_project_root_git_ancestor_env_and_cwd_fallback |
| gate-scripts.test.mjs | shell scripts are found for every way of running them | tests/test_gate_scripts.py::test_shell_scripts_found_for_every_way_of_running_them |
| gate-scripts.test.mjs | bash -c strings and stdin shells give no file | tests/test_gate_scripts.py::test_bash_c_strings_and_stdin_shells_give_no_file |
| gate-scripts.test.mjs | a cd inside a subshell or a substitution does not move later commands; popd goes back | tests/test_gate_scripts.py::test_cd_in_subshell_or_substitution_does_not_move_later_commands_popd_goes_back |
| gate-scripts.test.mjs | a sourced file is resolved against the directory the script ran in | tests/test_gate_scripts.py::test_sourced_file_resolved_against_the_directory_the_script_ran_in |
| gate-scripts.test.mjs | a cd after a shell string does not move the commands inside it | tests/test_gate_scripts.py::test_cd_after_shell_string_does_not_move_commands_inside_it |
| gate-scripts.test.mjs | shell strings given through wrappers and runners are followed | tests/test_gate_scripts.py::test_shell_strings_through_wrappers_and_runners_are_followed |
| gate-scripts.test.mjs | node targets: files, preloads, --test and --run | tests/test_gate_scripts.py::test_node_targets_files_preloads_test_and_run |
| gate-scripts.test.mjs | python, tsx and deno targets | tests/test_gate_scripts.py::test_python_tsx_and_deno_targets |
| gate-scripts.test.mjs | package scripts resolve from package.json in the cwd or -C/--dir/--prefix/--cwd | tests/test_gate_scripts.py::test_package_scripts_resolve_from_cwd_or_dir_options |
| gate-scripts.test.mjs | gh workflow run resolves a file name or a workflow name | tests/test_gate_scripts.py::test_gh_workflow_run_resolves_file_name_or_workflow_name |
| gate-scripts.test.mjs | source and import following: resolution, extensions, depth, cycles | tests/test_gate_scripts.py::test_source_and_import_following_resolution_extensions_depth_cycles |
| gate-scripts.test.mjs | a script that sources $SCRIPT_DIR/x resolves it against the script | tests/test_gate_scripts.py::test_script_sourcing_script_dir_resolves_against_the_script |
| gate-scripts.test.mjs | the 64 KB per-file cut is kept and reported as a problem | tests/test_gate_scripts.py::test_64_kb_per_file_cut_is_kept_and_reported_as_a_problem |
| gate-scripts.test.mjs | more than 32 files stops following and is a problem | tests/test_gate_scripts.py::test_more_than_32_files_stops_following_and_is_a_problem |
| gate-scripts.test.mjs | files outside the project, symlinks out and non-regular files are problems | tests/test_gate_scripts.py::test_files_outside_project_symlinks_out_and_non_regular_files_are_problems |
| gate-scripts.test.mjs | missing, glob and dynamic paths are skipped | tests/test_gate_scripts.py::test_missing_glob_and_dynamic_paths_are_skipped |
| gate-scripts.test.mjs | an unparsable command collects nothing | tests/test_gate_scripts.py::test_unparsable_command_collects_nothing |
| gate-scripts.test.mjs | scanScripts: program names, patterns and reasons | tests/test_gate_scripts.py::test_scan_scripts_program_names_patterns_and_reasons |
| gate-scripts.test.mjs | scanScripts: a workflow with a Acmecloud Actions step asks | tests/test_gate_scripts.py::test_scan_scripts_workflow_with_acmecloud_actions_step_asks |
| gate-scripts.test.mjs | scanScripts: a package script body that runs a gated program asks | tests/test_gate_scripts.py::test_scan_scripts_package_script_body_running_gated_program_asks |
| gate-scripts.test.mjs | exempt test files and their imports are not scanned | tests/test_gate_scripts.py::test_exempt_test_files_and_their_imports_are_not_scanned |
| gate-scripts.test.mjs | an exempt file that is too large does not ask | tests/test_gate_scripts.py::test_exempt_file_that_is_too_large_does_not_ask |
| gate-scripts.test.mjs | globToRegExp supports **/, **, * and ? | tests/test_gate_scripts.py::test_glob_to_regexp_supports_doublestar_slash_doublestar_star_and_question |
| gate-scripts.test.mjs | loadRules validates scriptPatterns and scriptScanExempt | tests/test_gate_scripts.py::test_load_rules_validates_script_patterns_and_script_scan_exempt |
| gate-scripts.test.mjs | terraform test sends the root module's and the test directory's *.tftest.hcl as exempt context | tests/test_gate_scripts.py::test_terraform_test_sends_root_and_test_dir_tftest_files_as_exempt_context |
| gate-scripts.test.mjs | terraform test sends nothing when the directory is unknown or not local | tests/test_gate_scripts.py::test_terraform_test_sends_nothing_when_directory_unknown_or_not_local |
| gate-scripts.test.mjs | variables assigned earlier in the command resolve script paths | tests/test_gate_scripts.py::test_variables_assigned_earlier_resolve_script_paths |
| jev-prompt.test.mjs | the default prompt is destructive and covers local and remote calls | tests/test_jev_prompt.py::test_default_prompt_is_destructive_and_covers_local_and_remote |
| jev-prompt.test.mjs | built-in prompts are valid and name no specific MCP server or product | tests/test_jev_prompt.py::test_builtin_prompts_valid_and_generic |
| jev-prompt.test.mjs | jevDecision with the destructive prompt | tests/test_jev_prompt.py::test_jev_decision_with_destructive_prompt |
| jev-prompt.test.mjs | askJev sends the destructive question and parses its answer | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| jev-prompt.test.mjs | GATE_JEV_PROMPT selects a built-in or a file | tests/test_jev_prompt.py::test_prompt_env_selects_builtin_or_file |
| jev-prompt.test.mjs | a relative GATE_JEV_PROMPT or GATE_JEV_LOG resolves against CLAUDE_PROJECT_DIR | dropped: replaced by the Jev-only hook (L1); rule tests go in L2 |
| jev-prompt.test.mjs | GATE_JEV_INSTRUCTIONS, GATE_JEV_CONTEXT and GATE_JEV_POLICY override the prompt | tests/test_jev_prompt.py::test_instructions_context_policy_override_prompt |
| jev-prompt.test.mjs | bad prompt settings fail with JevConfigError (the gate then asks) | tests/test_jev_prompt.py::test_bad_prompt_settings_raise_jev_config_error |
| packs.test.mjs | ported packs match the matching parts of the test ruleset | tests/test_packs.py::test_ported_packs_match_the_test_ruleset |
| packs.test.mjs | every pack loads on its own after base | tests/test_packs.py::test_every_pack_loads_after_base |
| packs.test.mjs | composeRules rejects duplicate rule ids and bad shapes | tests/test_packs.py::test_compose_rejects_duplicates_and_bad_shapes |
| packs.test.mjs | composeRules merges string lists without duplicates | tests/test_packs.py::test_compose_merges_string_lists_without_duplicates |
| packs.test.mjs | DEFAULT_PACKS is base + destructive | tests/test_packs.py::test_default_packs_is_base_and_destructive |
| packs.test.mjs | without GATE_RULES the hook loads the default packs | tests/test_packs.py::test_without_gate_rules_hook_loads_default_packs |
| readme.test.mjs | README documents every env variable the gate reads | tests/test_readme.py::test_readme_documents_every_env_variable |
| readme.test.mjs | README lists every built-in pack and Jev prompt | tests/test_readme.py::test_readme_lists_every_pack_and_jev_prompt |
