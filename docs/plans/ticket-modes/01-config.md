# Task 01: config keys and validation

Plan: [../ticket-modes.md](../ticket-modes.md) D5, §5.5, §6 (`config.md`), §7.
Depends on: –. Status: done.

## Goal

`.claude/gated-dev.json` accepts and validates `mode`, `modes` and
`modeRules`, with the defaults of D5.

## Read first

- `plugins/gated-dev-simple-workflow/scripts/gated_dev/launch/ticket_project.py`
  (`CONFIG_KEYS`, `read_config`, `_read_flow` as the pattern for a nested key)
- `plugins/gated-dev-simple-workflow/skills/ticket/references/config.md`

## Changes

1. `ticket_project.py`: add `mode`, `modes`, `modeRules` to `CONFIG_KEYS`.
2. Validate:
   - `mode`: `auto | heavy | medium | light`, default `auto`.
   - `modes`: object whose keys are only `heavy`, `medium`, `light`; each
     value an object whose only key is `session`; `session` a model alias
     (`opus`, `sonnet`, `haiku`) or a `claude-[a-z0-9.-]+` id. Defaults:
     heavy `opus`, medium `sonnet`, light `sonnet` (missing entries take
     the default).
   - `modeRules`: list of non-empty strings, default `[]`.
   Errors are `LaunchError` with the file name, like the existing checks.
3. Put the model check in one helper (task 02 reuses it for the shell line).
4. `references/config.md`: the table of D5; stage sets per mode are fixed
   and not configurable (say why in one line).

## Tests

In the existing config tests (`test_launch_units.py` or a new
`test_config_modes.py` if the file is crowded):

- defaults when the keys are missing;
- each valid `mode`; unknown mode rejected;
- `modes` with an unknown mode, an unknown inner key, a non-string or
  unsafe `session` (quote, space, `;`) rejected; partial `modes` merged with
  defaults;
- `modeRules` with a non-list or an empty string rejected.

## Done when

`uv run pytest plugins/gated-dev-simple-workflow` and `uv run ruff check .`
are green; `config.md` documents the three keys.
