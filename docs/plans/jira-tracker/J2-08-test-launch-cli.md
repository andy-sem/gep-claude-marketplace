# Task 08: `tests/test_launch_cli.py`

Package **J2** · prev [Task 07](J2-07-ticket-project.md) · next [Task 09](J2-09-launcher.md) · [index](README.md)

## Goal

An end-to-end CLI test (subprocess, as the file's other tests do) of `launch.py --dry-run` for a Jira key without `ticket.md`.

## Tests to add

1. `test_dry_run_tracker_key_without_ticket_file`: a git repo fixture (reuse the file's helper) with `.claude/gated-dev.json` = `{"tracker": {"type": "jira"}}` and no `docs/tickets/`. `--dry-run PROJ-7` exits 0 and prints mode `main-checkout` with the Jira note. The fake `orca`/`osascript` bins are not called.
2. `test_dry_run_tracker_rejects_non_jira_key`: `--dry-run add-csv` with the same config exits 1 with the `keyPattern` error (the tracker default pattern).
3. `test_invalid_tracker_config_exits_1`: `{"tracker": {"type": "linear"}}` gives exit 1 with `tracker.type` in stderr.
4. `test_all_with_tracker_lists_only_ticket_files`: `--all --dry-run` lists only keys that have a `ticket.md`. `--all` does not query Jira (the picker is out of scope).

## Steps

- [ ] **1.** Add the tests. Run `uv run pytest plugins/gated-dev-simple-workflow/tests/test_launch_cli.py`: 1 fails until Task 09; 2–4 pass already with Task 07 (that is fine; they pin behaviour).

## Done when

- The tests exist and fail only where Task 09 is still missing.
