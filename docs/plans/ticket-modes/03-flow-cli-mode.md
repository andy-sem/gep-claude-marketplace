# Task 03: flow CLI stores and shows the mode

Plan: [../ticket-modes.md](../ticket-modes.md) §5.1 (CLI part), §5.2, §7.
Depends on: 02. Status: not started.

## Goal

`flow.py launch ... --mode <mode>` launches the subtask's session with that
mode (via the launcher of task 02), stores the mode on the ticket in the
flow state, and `status` shows it.

## Read first

- `scripts/gated_dev/flow/{cli,state}.py` (`FlowState.add_launched`)
- `tests/test_flow_units.py`, `tests/test_flow_wait.py`

## Changes

1. `flow/cli.py`: `--mode heavy|medium|light` on `launch`; optional
   (without it, the session decides). Pass it through to the launcher.
2. `flow/state.py`: `add_launched(..., mode: str | None = None)`; stored on
   the ticket entry. Reading an older state file without `mode` works.
3. `status` output: mode per ticket (`-` when unknown).

## Tests

- `test_flow_units.py`: `launch --mode` stored in the state; old state
  without `mode` loads; invalid mode rejected.
- `test_flow_wait.py` (or units): `status` output carries the mode.

## Done when

Tests and ruff green.
