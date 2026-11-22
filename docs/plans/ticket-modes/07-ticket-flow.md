# Task 07: `/ticket-flow` decides and passes the mode

Plan: [../ticket-modes.md](../ticket-modes.md) §5.1, §7 (`test_flow_skill.py`).
Depends on: 03, 06. Status: not started.

## Goal

The flow driver decides each subtask's mode from the issue it just read and
launches it with `--mode`.

## Read first

- `skills/ticket-flow/SKILL.md`, `skills/ticket/references/flow.md`,
  `references/modes.md`
- `tests/test_flow_skill.py`

## Changes

1. `skills/ticket-flow/SKILL.md`: after the pick, decide the mode with the
   D2 rules (plus config `mode` and `modeRules`) and run
   `flow.py launch ... --mode <mode> --reason "<pick reason>; mode <mode>: <reason>"`.
   `--status` shows the mode per ticket.
2. `references/flow.md`: the same, next to the pick rules.

## Tests

`test_flow_skill.py`: extend the text checks so the skill mentions `--mode`
on launch.

## Done when

Tests green; the driver never launches without a mode.
