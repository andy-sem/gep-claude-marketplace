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
| check.test.mjs | checkCall never contacts Jev without --jev, and says when it would | tests/test_check.py::test_check_call_never_contacts_jev_without_flag |
| check.test.mjs | effectiveConfig: defaults, rule ids, Jev redaction, errors | tests/test_check.py::test_effective_config_defaults_ids_redaction_errors |
| check.test.mjs | CLI: text and JSON output, key never printed | tests/test_check.py::test_cli_text_and_json_output_key_never_printed |
| check.test.mjs | the skill's documented invocations pass the gate themselves | tests/test_check.py::test_documented_invocations_pass_the_gate |
| check.test.mjs | --cwd resolves scripts the command runs | tests/test_check.py::test_cwd_resolves_scripts_the_command_runs |
| check.test.mjs | checkCall: a relative GATE_RULES_FILE resolves against the git root of --cwd | tests/test_check.py::test_relative_rules_file_resolves_against_git_root_of_cwd |
| config.test.mjs | defaults: enabled, base + destructive, env guard on, not strict, no log | todo |
| config.test.mjs | boolean variables accept 0/1/true/false/yes/no/on/off and reject the rest | todo |
| config.test.mjs | GATE_CHECKS selects packs; base is always first and not duplicated | todo |
| config.test.mjs | GATE_CHECKS: unknown pack, none mixed with packs, none without a file -> ConfigError | todo |
| config.test.mjs | GATE_CHECKS=none + GATE_RULES_FILE is a full replacement | todo |
| config.test.mjs | GATE_RULES_FILE is appended after the default packs | todo |
| config.test.mjs | GATE_RULES (deprecated) replaces the packs and cannot be mixed | todo |
| config.test.mjs | GATE_DISABLE_RULES and GATE_LOG are read as given | todo |
| config.test.mjs | relative paths resolve against CLAUDE_PROJECT_DIR; absolute paths are kept | todo |
| config.test.mjs | without CLAUDE_PROJECT_DIR relative paths resolve against the git root of cwd, else cwd | todo |
| config.test.mjs | availablePacks lists the shipped packs | todo |
| config.test.mjs | buildRules: default packs ask on destructive commands only | todo |
| config.test.mjs | buildRules: optional packs and an extra rules file add rules | todo |
| config.test.mjs | buildRules: GATE_CHECKS=none + file loads only the file | todo |
| config.test.mjs | buildRules: GATE_DISABLE_RULES drops rules; unknown ids are an error | todo |
| config.test.mjs | buildRules: a missing or broken rules file is a RulesError | todo |
| config.test.mjs | strict: parser-uncertainty asks; loose: no opinion, other parts still checked | todo |
| config.test.mjs | hook: defaults ask on destructive, pass the rest | todo |
| config.test.mjs | hook: GATE_ENABLED=0 emits nothing, even for invalid input or config | todo |
| config.test.mjs | hook: bad configuration fails closed with gate-config | todo |
| config.test.mjs | hook: pack selection, extra file and disabled rules | todo |
| config.test.mjs | hook: a relative GATE_RULES_FILE works after the session cd'ed into a subdirectory | todo |
| config.test.mjs | hook: GATE_LOG appends one redacted JSON line per decision | todo |
| config.test.mjs | hook: GATE_LOG is not written when the gate is off, and a bad path never breaks the gate | todo |
| config.test.mjs | env guard matches env file names only | todo |
| config.test.mjs | env guard is off with GATE_ENV_GUARD=0 or GATE_ENABLED=0, on for other values | todo |
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
| gate-engine.test.mjs | classify: ${label} -> ${expected} | todo |
| gate-engine.test.mjs | allowlist reasons name the write verb | todo |
| gate-engine.test.mjs | dynamic arguments name the reason | todo |
| gate-engine.test.mjs | loadRules accepts legacy and object runners and rejects bad ones | todo |
| gate-engine.test.mjs | shell reading stdin is unparsable, with a reason | todo |
| gate-engine.test.mjs | non-object input fails closed | todo |
| gate-engine.test.mjs | splitCommand returns one token list per simple command | todo |
| gate-engine.test.mjs | loadRules throws RulesError on bad config | todo |
| gate-engine.test.mjs | loadRules ignores a leftover protectedBranches and rejects removed kinds | todo |
| gate-engine.test.mjs | loadRules fails closed on a malformed inertUnsafeFlags | todo |
| gate-engine.test.mjs | CLI: emits ask for a gated command and exits 0 | todo |
| gate-engine.test.mjs | CLI: prints nothing for a non-gated command | todo |
| gate-engine.test.mjs | CLI: subagent calls (agent_id) still get ask | todo |
| gate-engine.test.mjs | CLI: broken rules file asks with gate-config for every call | todo |
| gate-engine.test.mjs | CLI: unparsable stdin asks (fails closed) | todo |
| gate-hook.test.mjs | gated command -> ask | tests/test_gate_hook.py::test_gated_command_asks |
| gate-hook.test.mjs | git status -> empty stdout, exit 0 | tests/test_gate_hook.py::test_git_status_passes |
| gate-hook.test.mjs | non-JSON stdin -> ask unparsable | tests/test_gate_hook.py::test_non_json_stdin_asks_unparsable |
| gate-hook.test.mjs | invalid rules file -> ask gate-config | tests/test_gate_hook.py::test_invalid_rules_file_asks_gate_config |
| gate-hook.test.mjs | node unavailable -> ask | tests/test_gate_hook.py::test_interpreter_unavailable_asks |
| gate-hook.test.mjs | engine exits non-zero after partial JSON -> fixed ask only | tests/test_gate_hook.py::test_engine_partial_json_then_nonzero_gives_fixed_ask |
| gate-hook.test.mjs | engine exits 0 with empty stdout but did not run -> ask | tests/test_gate_hook.py::test_engine_exit_0_without_running_asks |
| gate-hook.test.mjs | empty stdin -> ask | tests/test_gate_hook.py::test_empty_stdin_asks |
| gate-hook.test.mjs | script scan: a script that runs terraform asks with script: | tests/test_gate_hook.py::test_script_scan_terraform_script_asks |
| gate-hook.test.mjs | script scan: a provision script that imports a cloudctl module asks with script: | tests/test_gate_hook.py::test_script_scan_provision_script_importing_cloudctl_asks |
| gate-hook.test.mjs | script scan: a Cloudflare-only script passes | tests/test_gate_hook.py::test_script_scan_cloudflare_only_script_passes |
| gate-hook.test.mjs | terraform rule: apply, destroy and import ask with terraform: | tests/test_gate_hook.py::test_terraform_rule_asks |
| gate-hook.test.mjs | fallback passes: terraform plan/fmt/validate, --help, tests and git push | tests/test_gate_hook.py::test_fallback_passes |
| gate-hook.test.mjs | GATE_JEV unset -> rules-only output | tests/test_gate_hook_jev.py::test_jev_unset_gives_rules_only_output |
| gate-hook.test.mjs | jev: rule-matched command classified read_only 0.97 -> empty output | tests/test_gate_hook_jev.py::test_rule_matched_read_only_097_passes |
| gate-hook.test.mjs | jev: in-scope command no rule matched, risk 0.55 -> ask | tests/test_gate_hook_jev.py::test_in_scope_no_rule_risk_055_asks |
| gate-hook.test.mjs | jev: a command outside every rule's programs goes to Jev and its risk asks | tests/test_gate_hook_jev.py::test_command_outside_rule_programs_goes_to_jev |
| gate-hook.test.mjs | jev: read_only 0.90 -> rule result stands | tests/test_gate_hook_jev.py::test_read_only_090_rule_result_stands |
| gate-hook.test.mjs | jev: unparsable command classified read_only 0.97 -> empty output | tests/test_gate_hook_jev.py::test_unparsable_read_only_097_passes |
| gate-hook.test.mjs | jev: unparsable command classified risky -> jev ask | tests/test_gate_hook_jev.py::test_unparsable_risky_asks_jev |
| gate-hook.test.mjs | jev: unsure or unreachable on unparsable command -> unparsable ask (GATE_STRICT=1) | tests/test_gate_hook_jev.py::test_unsure_or_unreachable_unparsable_asks_strict |
| gate-hook.test.mjs | jev: unparsable command without Jev asks with GATE_STRICT=1 | tests/test_gate_hook_jev.py::test_unparsable_without_jev_asks_strict |
| gate-hook.test.mjs | jev: unparsable command by default (GATE_STRICT unset) -> no opinion | tests/test_gate_hook_jev.py::test_unparsable_default_no_opinion |
| gate-hook.test.mjs | jev: input-level unparsable and gate-config results still ask | tests/test_gate_hook_jev.py::test_input_level_unparsable_and_gate_config_still_ask |
| gate-hook.test.mjs | jev: missing TYPESAFE_API_KEY -> ask gate-config | tests/test_gate_hook_jev.py::test_missing_api_key_asks_gate_config |
| gate-hook.test.mjs | jev: unreachable service -> rule result stands | tests/test_gate_hook_jev.py::test_unreachable_service_rule_result_stands |
| gate-hook.test.mjs | the gate hook stays registered for Bash and every MCP tool only | tests/test_gate_hook.py::test_hook_registered_for_bash_and_mcp_only |
| gate-hook.test.mjs | jev: every Bash and MCP call makes exactly one request; file tools make none | tests/test_gate_hook_jev.py::test_every_bash_and_mcp_call_one_request_file_tools_none |
| gate-hook.test.mjs | jev: risk above 0.5 asks for Bash and MCP calls no rule matched | tests/test_gate_hook_jev.py::test_risk_above_05_asks_when_no_rule_matched |
| gate-hook.test.mjs | jev: unrelated 0.97 gives no output | tests/test_gate_hook_jev.py::test_unrelated_097_gives_no_output |
| gate-hook.test.mjs | jev: read_only 0.97 lifts rule asks and script asks | tests/test_gate_hook_jev.py::test_read_only_097_lifts_rule_and_script_asks |
| gate-hook.test.mjs | jev: GATE_JEV_SCOPE limits which calls are sent | tests/test_gate_hook_jev.py::test_scope_limits_which_calls_are_sent |
| gate-hook.test.mjs | jev: GATE_JEV_CAN_LIFT=0 keeps rule asks, Jev still adds asks | tests/test_gate_hook_jev.py::test_can_lift_0_keeps_rule_asks_jev_still_adds |
| gate-hook.test.mjs | jev: invalid GATE_JEV_SCOPE or GATE_JEV_CAN_LIFT asks gate-config | tests/test_gate_hook_jev.py::test_invalid_scope_or_can_lift_asks_gate_config |
| gate-hook.test.mjs | jev: the request for a script carries the redacted script | tests/test_gate_hook_jev.py::test_script_request_carries_redacted_script |
| gate-hook.test.mjs | jev: terraform test sends its test files and Jev can lift the terraform ask | tests/test_gate_hook_jev.py::test_terraform_test_sends_test_files_and_jev_can_lift |
| gate-hook.test.mjs | jev: files the gate could not read reach Jev as notes | tests/test_gate_hook_jev.py::test_unreadable_files_reach_jev_as_notes |
| gate-hook.test.mjs | jev: imports are followed to depth 3, with per-file and total caps | tests/test_gate_hook_jev.py::test_imports_followed_to_depth_3_with_caps |
| gate-hook.test.mjs | jev: a provision script is sent with its imports | tests/test_gate_hook_jev.py::test_provision_script_sent_with_imports |
| gate-hook.test.mjs | jev: MCP calls send the tool name and the redacted input | tests/test_gate_hook_jev.py::test_mcp_calls_send_tool_name_and_redacted_input |
| gate-hook.test.mjs | jev failures give the rule result for Bash and MCP calls | tests/test_gate_hook_jev.py::test_jev_failures_give_rule_result |
| gate-hook.test.mjs | jev: an MCP call without its args and a gate-config result never reach Jev | tests/test_gate_hook_jev.py::test_mcp_without_args_and_gate_config_never_reach_jev |
| gate-hook.test.mjs | jev audit log: records carry tool, usage and latencyMs | tests/test_gate_hook_jev.py::test_audit_log_records_tool_usage_latency |
| gate-jev.test.mjs | redact returns null for commands referencing .env files | todo |
| gate-jev.test.mjs | redact strips URL credentials | todo |
| gate-jev.test.mjs | redact strips Bearer, Basic and Token values | todo |
| gate-jev.test.mjs | redact strips secret-named NAME=value and NAME: value | todo |
| gate-jev.test.mjs | redact strips --password style flag values | todo |
| gate-jev.test.mjs | redact strips environment assignments | todo |
| gate-jev.test.mjs | redact strips long hex runs | todo |
| gate-jev.test.mjs | redact strips long mixed-case base64 runs | todo |
| gate-jev.test.mjs | redact leaves ordinary commands unchanged | todo |
| gate-jev.test.mjs | readJevConfig returns null when GATE_JEV is off | todo |
| gate-jev.test.mjs | readJevConfig applies defaults | todo |
| gate-jev.test.mjs | readJevConfig reads GATE_JEV_SCOPE and GATE_JEV_CAN_LIFT | todo |
| gate-jev.test.mjs | readJevConfig treats empty optional vars as unset | todo |
| gate-jev.test.mjs | readJevConfig reads overrides | todo |
| gate-jev.test.mjs | readJevConfig throws JevConfigError on invalid input | todo |
| gate-jev.test.mjs | readJevConfig accepts loopback http URLs | todo |
| gate-jev.test.mjs | jevDecision passes confident read_only and unrelated | todo |
| gate-jev.test.mjs | jevDecision sums unrelated and read_only for the safe side | todo |
| gate-jev.test.mjs | jevDecision returns null when the safe side is below the threshold | todo |
| gate-jev.test.mjs | jevDecision asks when risk exceeds the escalate threshold | todo |
| gate-jev.test.mjs | jevDecision does not ask at exactly the escalate threshold | todo |
| gate-jev.test.mjs | jevDecision names cloud_or_data_change when it is larger | todo |
| gate-jev.test.mjs | parseAnswer accepts a well-formed answer | todo |
| gate-jev.test.mjs | parseAnswer returns null for malformed shapes | todo |
| gate-jev.test.mjs | askJev returns probabilities, usage and latency and sends a well-formed request | todo |
| gate-jev.test.mjs | askJev has a latency on errors too | todo |
| gate-jev.test.mjs | askJev reports usage null when Jev sends none | todo |
| gate-jev.test.mjs | askJev reports non-retryable http errors | todo |
| gate-jev.test.mjs | askJev retries 429 and then succeeds | todo |
| gate-jev.test.mjs | askJev gives up when retry-after exceeds the budget | todo |
| gate-jev.test.mjs | askJev times out when fetch hangs until aborted | todo |
| gate-jev.test.mjs | askJev reports network failures | todo |
| gate-jev.test.mjs | askJev reports malformed bodies | todo |
| gate-jev.test.mjs | runJev returns the rule result unchanged when Jev fails | todo |
| gate-jev.test.mjs | runJev with canLift false keeps rule asks but still adds asks | todo |
| gate-jev.test.mjs | runJev falls back to the rule result for every failure mode | todo |
| gate-jev.test.mjs | runJev never sends Bash commands that reference .env | todo |
| gate-jev.test.mjs | runJev lifts a rule ask when Jev passes, for Bash and MCP | todo |
| gate-jev.test.mjs | runJev asks even when the rules had no opinion | todo |
| gate-jev.test.mjs | runJev keeps the rule result when Jev is undecided | todo |
| gate-jev.test.mjs | runJev sends the Bash payload with scripts and notes | todo |
| gate-jev.test.mjs | buildState caps the command and notes the cut | todo |
| gate-jev.test.mjs | buildState caps scripts at 64 KB in total and notes it | todo |
| gate-jev.test.mjs | buildState notes a file cut at the per-file cap | todo |
| gate-jev.test.mjs | runJev sends the MCP payload with a cut note | todo |
| gate-jev.test.mjs | redactScript removes .env lines, redacts secrets and keeps the call | todo |
| gate-jev.test.mjs | redactMcpInput redacts SQL literals but keeps the statement and plain ids | todo |
| gate-jev.test.mjs | redactMcpInput replaces dollar-quoted bodies | todo |
| gate-jev.test.mjs | redactMcpInput redacts secret keys, Bearer values and .env mentions in nested JSON | todo |
| gate-jev.test.mjs | redactMcpInput handles an empty input | todo |
| gate-jev.test.mjs | runJev writes a redacted JSONL audit log with tool, usage and latency | todo |
| gate-rules.test.mjs | loadRules accepts the shipped rule file | tests/test_corpus.py::test_shipped_rule_file_loads |
| gate-rules.test.mjs | wrangler, pulumi, cf-apply scripts and git push are not gated | tests/test_corpus.py::test_gate_rules_case |
| gate-rules.test.mjs | ${label} -> ${expected} | tests/test_corpus.py::test_gate_rules_case |
| gate-scripts.test.mjs | findProjectRoot finds the .git ancestor, falling back to the env and the cwd | todo |
| gate-scripts.test.mjs | shell scripts are found for every way of running them | todo |
| gate-scripts.test.mjs | bash -c strings and stdin shells give no file | todo |
| gate-scripts.test.mjs | a cd inside a subshell or a substitution does not move later commands; popd goes back | todo |
| gate-scripts.test.mjs | a sourced file is resolved against the directory the script ran in | todo |
| gate-scripts.test.mjs | a cd after a shell string does not move the commands inside it | todo |
| gate-scripts.test.mjs | shell strings given through wrappers and runners are followed | todo |
| gate-scripts.test.mjs | node targets: files, preloads, --test and --run | todo |
| gate-scripts.test.mjs | python, tsx and deno targets | todo |
| gate-scripts.test.mjs | package scripts resolve from package.json in the cwd or -C/--dir/--prefix/--cwd | todo |
| gate-scripts.test.mjs | gh workflow run resolves a file name or a workflow name | todo |
| gate-scripts.test.mjs | source and import following: resolution, extensions, depth, cycles | todo |
| gate-scripts.test.mjs | a script that sources $SCRIPT_DIR/x resolves it against the script | todo |
| gate-scripts.test.mjs | the 64 KB per-file cut is kept and reported as a problem | todo |
| gate-scripts.test.mjs | more than 32 files stops following and is a problem | todo |
| gate-scripts.test.mjs | files outside the project, symlinks out and non-regular files are problems | todo |
| gate-scripts.test.mjs | missing, glob and dynamic paths are skipped | todo |
| gate-scripts.test.mjs | an unparsable command collects nothing | todo |
| gate-scripts.test.mjs | scanScripts: program names, patterns and reasons | todo |
| gate-scripts.test.mjs | scanScripts: a workflow with a Acmecloud Actions step asks | todo |
| gate-scripts.test.mjs | scanScripts: a package script body that runs a gated program asks | todo |
| gate-scripts.test.mjs | exempt test files and their imports are not scanned | todo |
| gate-scripts.test.mjs | an exempt file that is too large does not ask | todo |
| gate-scripts.test.mjs | globToRegExp supports **/, **, * and ? | todo |
| gate-scripts.test.mjs | loadRules validates scriptPatterns and scriptScanExempt | todo |
| gate-scripts.test.mjs | terraform test sends the root module's and the test directory's *.tftest.hcl as exempt context | todo |
| gate-scripts.test.mjs | terraform test sends nothing when the directory is unknown or not local | todo |
| gate-scripts.test.mjs | variables assigned earlier in the command resolve script paths | todo |
| jev-prompt.test.mjs | the default prompt is destructive and covers local and remote calls | tests/test_jev_prompt.py::test_default_prompt_is_destructive_and_covers_local_and_remote |
| jev-prompt.test.mjs | built-in prompts are valid and name no specific MCP server or product | tests/test_jev_prompt.py::test_builtin_prompts_valid_and_generic |
| jev-prompt.test.mjs | jevDecision with the destructive prompt | tests/test_jev_prompt.py::test_jev_decision_with_destructive_prompt |
| jev-prompt.test.mjs | askJev sends the destructive question and parses its answer | tests/test_jev_prompt.py::test_ask_jev_sends_destructive_question |
| jev-prompt.test.mjs | GATE_JEV_PROMPT selects a built-in or a file | tests/test_jev_prompt.py::test_prompt_env_selects_builtin_or_file |
| jev-prompt.test.mjs | a relative GATE_JEV_PROMPT or GATE_JEV_LOG resolves against CLAUDE_PROJECT_DIR | tests/test_jev_prompt.py::test_relative_prompt_and_log_resolve_against_project_dir |
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
