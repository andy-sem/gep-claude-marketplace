# Porting map: gated-dev-simple-workflow

One row per JS test (`test/*.test.mjs`). The last column says where the Python
port lives: `todo`, `dropped: <reason>`, or `<path relative to the plugin>::<test_name>`
(several targets separated by `, `). `tests/test_porting.py` checks that every JS
test has a row and that every target exists.

| JS file | JS test | Python test |
| --- | --- | --- |
| launch.test.mjs | buildShellCommand quotes cwd, sets TICKET_FLOW_KEY and names the session | tests/test_launch_units.py::test_build_shell_command_quotes_cwd_sets_key_and_names_the_session |
| launch.test.mjs | buildShellCommand escapes single quotes in cwd | tests/test_launch_units.py::test_build_shell_command_escapes_single_quotes_in_cwd |
| launch.test.mjs | buildShellCommand rejects unsafe keys, other args, relative cwd, bad remoteControl | tests/test_launch_units.py::test_build_shell_command_rejects_unsafe_keys, tests/test_launch_units.py::test_build_shell_command_rejects_other_args_relative_cwd_bad_remote_control |
| launch.test.mjs | shortSummary strips unsafe characters and cuts at a word boundary | tests/test_launch_units.py::test_short_summary_strips_unsafe_characters_and_cuts_at_a_word_boundary |
| launch.test.mjs | sessionName: key, resume and summary | tests/test_launch_units.py::test_session_name_key_resume_and_summary |
| launch.test.mjs | a hostile title cannot reach the shell or AppleScript | tests/test_launch_units.py::test_a_hostile_title_cannot_reach_the_shell_or_applescript |
| launch.test.mjs | slugify follows the skill rule | tests/test_launch_units.py::test_slugify_follows_the_skill_rule |
| launch.test.mjs | detectHost: TERM_PROGRAM first, then Orca handle, then iTerm2 session id | tests/test_launch_units.py::test_detect_host_term_program_first_then_orca_handle_then_iterm_session |
| launch.test.mjs | iTermSessionId takes the GUID and ignores unusable values | tests/test_launch_units.py::test_iterm_session_id_takes_the_guid_and_ignores_unusable_values |
| launch.test.mjs | buildAppleScript escapes, names the tab and targets the launcher's window | tests/test_launch_units.py::test_build_applescript_escapes_names_the_tab_and_targets_the_launchers_window |
| launch.test.mjs | buildOrcaArgs: selector, then the launcher's workspace, then the path | tests/test_launch_units.py::test_build_orca_args_selector_then_launchers_workspace_then_path |
| launch.test.mjs | readConfig: defaults, overrides and invalid content | tests/test_launch_units.py::test_read_config_defaults_overrides_and_invalid_content |
| launch.test.mjs | checkKey applies keyPattern and the safe character set | tests/test_launch_units.py::test_check_key_applies_key_pattern_and_the_safe_character_set |
| launch.test.mjs | readTicket: title, front matter base, missing file and missing title | tests/test_launch_units.py::test_read_ticket_title_front_matter_base_missing_file_and_missing_title |
| launch.test.mjs | listTicketKeys lists ticket dirs whose key matches | tests/test_launch_units.py::test_list_ticket_keys_lists_ticket_dirs_whose_key_matches |
| launch.test.mjs | findRun finds the <KEY>/* worktree, ignores aborted runs, rejects several | tests/test_launch_cli.py::test_find_run_finds_the_key_worktree_ignores_aborted_runs_rejects_several |
| launch.test.mjs | resolveBase: front matter, config, origin/HEAD, main | tests/test_launch_cli.py::test_resolve_base_front_matter_config_origin_head_main |
| launch.test.mjs | orcaWorktreeArgs names the worktree and branch after key and title | tests/test_launch_units.py::test_orca_worktree_args_name_the_worktree_and_branch_after_key_and_title |
| launch.test.mjs | createOrcaWorktree copies local settings and the ticket into the worktree | tests/test_launch_cli.py::test_create_orca_worktree_copies_local_settings_and_the_ticket |
| launch.test.mjs | createOrcaWorktree keeps a ticket the base branch carries, reads other JSON shapes | tests/test_launch_cli.py::test_create_orca_worktree_keeps_a_ticket_the_base_branch_carries_reads_other_json_shapes |
| launch.test.mjs | createOrcaWorktree rejects output without JSON or without a path | tests/test_launch_cli.py::test_create_orca_worktree_rejects_output_without_json_or_without_a_path |
| launch.test.mjs | launchTab in iTerm2 runs osascript with -e lines targeting the launcher's session | tests/test_launch_cli.py::test_launch_tab_in_iterm_runs_osascript_with_e_lines_targeting_the_launchers_session |
| launch.test.mjs | launchTab in Orca creates the terminal, then renames it | tests/test_launch_cli.py::test_launch_tab_in_orca_creates_the_terminal_then_renames_it |
| launch.test.mjs | launchTab in Orca: no handle means no rename; a failed rename is only logged | tests/test_launch_cli.py::test_launch_tab_in_orca_no_handle_means_no_rename_a_failed_rename_is_only_logged |
| launch.test.mjs | launchTicket in Orca: fetch, Orca worktree, tab in that worktree | tests/test_launch_cli.py::test_launch_ticket_in_orca_fetch_orca_worktree_tab_in_that_worktree |
| launch.test.mjs | launchTicket in Orca uses front matter base before config and origin/HEAD | tests/test_launch_cli.py::test_launch_ticket_in_orca_uses_front_matter_base_before_config_and_origin_head |
| launch.test.mjs | launchTicket in Orca with an unregistered repo opens in the main checkout | tests/test_launch_cli.py::test_launch_ticket_in_orca_with_an_unregistered_repo_opens_in_the_main_checkout |
| launch.test.mjs | launchTicket in iTerm2 opens the main checkout and runs only osascript | tests/test_launch_cli.py::test_launch_ticket_in_iterm_opens_the_main_checkout_and_runs_only_osascript |
| launch.test.mjs | launchTicket resumes an existing run in its worktree | tests/test_launch_cli.py::test_launch_ticket_resumes_an_existing_run_in_its_worktree |
| launch.test.mjs | launchTicket resumes a finished run (restarts the PR watch) | tests/test_launch_cli.py::test_launch_ticket_resumes_a_finished_run_and_restarts_the_pr_watch |
| launch.test.mjs | launchTicket dry run changes nothing and plans the Orca worktree | tests/test_launch_cli.py::test_launch_ticket_dry_run_changes_nothing_and_plans_the_orca_worktree |
| launch.test.mjs | launchTicket outside Orca/iTerm2 fails unless it is a dry run | tests/test_launch_cli.py::test_launch_ticket_outside_orca_and_iterm_fails_unless_it_is_a_dry_run |
| launch.test.mjs | launchTicket: a failing orca worktree create throws and never falls back | tests/test_launch_cli.py::test_launch_ticket_a_failing_orca_worktree_create_throws_and_never_falls_back |
| launch.test.mjs | launchTicket rejects a key outside keyPattern and a ticket without a file | tests/test_launch_cli.py::test_launch_ticket_rejects_a_key_outside_key_pattern_and_a_ticket_without_a_file |
| launch.test.mjs | launchTicket with orchestratorRules starts a ticket without ticket.md in the main checkout | tests/test_launch_cli.py::test_launch_ticket_with_orchestrator_rules_starts_a_ticket_without_ticket_md_in_the_main_checkout |
| launch.test.mjs | parseArgs: keys or --all, flags, errors | tests/test_launch_units.py::test_parse_args_keys_or_all_flags_errors |
| launch.test.mjs | main --all --dry-run plans every ticket without a run and reports failures per key | tests/test_launch_cli.py::test_main_all_dry_run_plans_every_ticket_without_a_run_and_reports_failures_per_key |
| launch.test.mjs | main reports a config error and a usage error | tests/test_launch_cli.py::test_main_reports_a_config_error_and_a_usage_error |
| notify.test.mjs | hooks.json registers notify.sh for Notification | tests/test_notify.py::test_hooks_json_registers_notification_hook |
| notify.test.mjs | silent without TICKET_FLOW_KEY | tests/test_notify.py::test_silent_without_ticket_flow_key |
| notify.test.mjs | GATED_DEV_NOTIFY=0 turns it off | tests/test_notify.py::test_notify_off_switch |
| notify.test.mjs | macOS: osascript with key title and the event message | tests/test_notify.py::test_macos_osascript_with_key_title_and_event_message |
| notify.test.mjs | Linux: notify-send with key title and the event message | tests/test_notify.py::test_linux_notify_send_with_key_title_and_event_message |
| notify.test.mjs | Linux without notify-send: silent, exit 0 | tests/test_notify.py::test_linux_without_notify_send_is_silent |
| notify.test.mjs | other OS: silent, exit 0 | tests/test_notify.py::test_other_os_is_silent |
| notify.test.mjs | default message without jq or with bad input | tests/test_notify.py::test_default_message_on_bad_input |
| notify.test.mjs | a failing notifier does not fail the hook | tests/test_notify.py::test_a_failing_notifier_does_not_fail_the_hook |
| notify.test.mjs | direct mode: title and message from arguments, no TICKET_FLOW_KEY needed | tests/test_notify.py::test_direct_mode_title_and_message_from_arguments |
| watch-pr.test.mjs | a human issue comment newer than the PR creation exits with feedback | tests/test_watch_pr.py::test_human_issue_comment_newer_than_pr_creation_is_feedback |
| watch-pr.test.mjs | a review and an inline comment count as feedback | tests/test_watch_pr.py::test_review_and_inline_comment_count_as_feedback |
| watch-pr.test.mjs | the cutoff is lastAddressedCommentAt, else the PR creation time | tests/test_watch_pr.py::test_cutoff_is_last_addressed_comment_else_pr_creation |
| watch-pr.test.mjs | a cutoff written to the file between polls is honoured | tests/test_watch_pr.py::test_cutoff_written_to_the_file_between_polls_is_honoured |
| watch-pr.test.mjs | bots, pipeline replies, empty comments and empty reviews never exit | tests/test_watch_pr.py::test_bots_pipeline_replies_empty_comments_and_reviews_never_exit |
| watch-pr.test.mjs | MERGED and CLOSED exit with their outcome | tests/test_watch_pr.py::test_merged_and_closed_exit_with_their_outcome |
| watch-pr.test.mjs | MERGED wins over feedback | tests/test_watch_pr.py::test_merged_wins_over_feedback |
| watch-pr.test.mjs | five consecutive gh failures exit with error | tests/test_watch_pr.py::test_five_consecutive_gh_failures_exit_with_error |
| watch-pr.test.mjs | four failures, a success, four failures do not exit | tests/test_watch_pr.py::test_four_failures_a_success_four_failures_do_not_exit |
| watch-pr.test.mjs | a missing or invalid state.json counts as a failed poll | tests/test_watch_pr.py::test_missing_or_invalid_state_counts_as_a_failed_poll |
| watch-pr.test.mjs | every poll writes the heartbeat and keeps every other field | tests/test_watch_pr.py::test_every_poll_writes_the_heartbeat_and_keeps_every_other_field |
| watch-pr.test.mjs | the heartbeat is written after a failed poll too | tests/test_watch_pr.py::test_heartbeat_is_written_after_a_failed_poll_too |
| watch-pr.test.mjs | startedAt stays the first poll time while heartbeatAt advances | tests/test_watch_pr.py::test_started_at_stays_the_first_poll_time_while_heartbeat_advances |
| watch-pr.test.mjs | every sleep is 60000 ms and only gh is run | tests/test_watch_pr.py::test_every_sleep_is_60000_ms_and_only_gh_is_run |
| watch-pr.test.mjs | a failed heartbeat write is logged and does not stop the watcher | tests/test_watch_pr.py::test_failed_heartbeat_write_is_logged_and_does_not_stop_the_watcher |
| watch-pr.test.mjs | main prints one JSON line and returns the exit code per outcome | tests/test_watch_pr.py::test_main_prints_one_json_line_and_exits_per_outcome |
| watch-pr.test.mjs | main returns 2 with a usage line for a missing or relative --state | tests/test_watch_pr.py::test_main_exits_2_with_a_usage_line_for_missing_or_relative_state |
| watch-pr.test.mjs | parsePrUrl and normalizePr | tests/test_watch_pr_units.py::test_parse_pr_url_and_normalize_pr |
| watch-pr.test.mjs | a PR url that cannot be parsed counts as a failed poll | tests/test_watch_pr.py::test_pr_url_that_cannot_be_parsed_counts_as_a_failed_poll |
| watch-pr.test.mjs | the watcher command passes destructive-guard with its defaults | dropped: the gate no longer has deterministic rules (L2); L5 revisits it |
