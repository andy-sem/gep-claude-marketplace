# Task 01: config `devTier` and tier models

Plan: [../dev-tiers.md](../dev-tiers.md) D5, §3 (ticket_project.py, config.md), §4.
Depends on: –. Status: not started.

## Goal

`.claude/gated-dev.json` accepts `devTier` and `models.devGodzilla`,
`models.devWorkhorse`, `models.devPawn`; `models.dev` stops with a clear
message.

## Read first

- `plugins/gated-dev-simple-workflow/scripts/gated_dev/launch/ticket_project.py`
  (today `models` is only checked as a known top-level key)
- `skills/ticket/references/config.md`, SKILL.md §0 (the model keys it
  already uses, e.g. `models.reviewRisk`)

## Changes

1. `ticket_project.py`:
   - `devTier` in `CONFIG_KEYS`; values `auto | godzilla | workhorse | pawn`,
     default `auto`;
   - validate `models`: an object with a known key set (the existing keys
     from SKILL.md §0 plus the three tier keys), each value a model alias or
     `claude-[a-z0-9.-]+` id (reuse the ticket-modes helper if it exists);
   - `models.dev` present → `LaunchError`: "`models.dev` was replaced by
     `models.devWorkhorse` (and `devGodzilla`, `devPawn`)";
   - defaults: `opus` / `sonnet` / `haiku`.
2. `references/config.md`: D5 table; remove `models.dev`.

## Tests

- `devTier` defaults, each valid value, unknown value rejected;
- `models` unknown key, wrong type, unsafe model string rejected;
- `models.dev` gives exactly the message above;
- tier model defaults.

## Done when

`uv run pytest plugins/gated-dev-simple-workflow` and ruff green.
