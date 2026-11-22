# Task 02: launcher starts the session model and passes `--mode`

Plan: [../ticket-modes.md](../ticket-modes.md) D4, §5.3, §5.4, §5.6, §5.7, §7.
Depends on: 01. Status: not started.

## Goal

`launch.py` can start a ticket session as `claude --model <model> ...` with
`/ticket KEY --mode <mode>` in the prompt, and a resume starts on the
session model of the run's recorded mode.

## Read first

- `scripts/gated_dev/launch/{cli,terminal,orca,launcher}.py`
- `skills/launch/SKILL.md`
- `tests/test_launch_units.py`, `tests/test_launch_cli.py`

(paths under `plugins/gated-dev-simple-workflow/`)

## Changes

1. `terminal.py` `build_shell_command`: new keyword `model` (default `None`
   = no `--model`, today's behaviour). The value goes through the model
   check of task 01 before it reaches the shell line; anything else raises.
   Output: `claude --model <model> --name ...`.
2. The Orca launch path builds its command the same way (`orca.py`).
3. `cli.py`:
   - `--mode heavy|medium|light`, applies to all keys of the call;
   - `ALLOWED_ARGS` gets `--mode` (with its value) next to `--resume`;
   - with `--mode`, the model is `modes.<mode>.session` from the config;
     without it, no `--model` (the session decides the mode itself, D1);
   - `--mode` together with `--resume` is refused (the recorded mode wins);
   - resume: read `mode` from the run's `state.json`; when present, start
     with that mode's session model; when missing (old run), no `--model`.
4. Dry run prints the model and the mode per key.
5. `skills/launch/SKILL.md`: document `--mode`, the model rule and the
   dry-run output.

## Tests

- `test_launch_units.py`: `build_shell_command` with an alias, a full
  `claude-...` id, `None`; rejected values with quotes, spaces, `$(`;
  `--mode <mode>` lands in the `/ticket` prompt.
- `test_launch_cli.py`: `--mode` parsing and bad values; dry run shows model
  and mode; config `modes.light.session` override is used; `--resume` picks
  the recorded mode's model; `--resume --mode` refused; resume of a run
  without `mode` starts without `--model`.

## Done when

Tests and ruff green. No `/ticket` behaviour depends on this yet; do not
release before task 06.
