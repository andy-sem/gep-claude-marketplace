# Task 08: README, versions, manual check

Plan: [../ticket-modes.md](../ticket-modes.md) §6, §8, §11.
Depends on: 01–07. Status: done.

Note: the manual check below (private demo repo) is still to be done by the user.

## Goal

The feature is documented for users, versioned, and checked by hand.

## Changes

1. Plugin README: user-facing description of the modes (table, how the mode
   is chosen and raised, `--mode`, config keys) and an entry in "Design
   decisions and history" (decisions of 2026-11-22 included).
2. `plugins/gated-dev-simple-workflow/.claude-plugin/plugin.json` and the
   catalog entry in `.claude-plugin/marketplace.json`: version 0.13.0 (or
   the next minor if dev tiers shipped first), description mentions modes;
   bump `metadata.version`.
3. CLAUDE.md: one line on modes in the `gated-dev-simple-workflow` section.
4. Ask the user about open question O1 (may `modes.light.session` be
   `haiku`; default stays `sonnet`) before writing the README text on it.

## Manual check (private demo repo, not in this repo)

- one ticket per mode, started by hand;
- one Jira parent through `/ticket-flow` with small and large subtasks;
- a light ticket whose diff touches `riskPaths` (review gets added);
- a planner raise to heavy before H2;
- a hand-started Sonnet session that decides heavy (restart question);
- `--resume` of a light run.

## Done when

`claude plugin validate .`, `jq . .claude-plugin/marketplace.json`,
`uv run pytest`, `uv run ruff check .` green; manual check done and noted
in the PR.
