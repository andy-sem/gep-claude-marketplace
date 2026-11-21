# Task 10: `scripts/gated_dev/launch/cli.py`

Package **J2** · prev [Task 09](J2-09-launcher.md) · next [Task 11](J3-11-launch-skill.md) · [index](README.md)

## Goal

The `--help` text mentions that tracker keys need no `ticket.md`.

## Change

In the usage text of `LaunchCli` (line ~28), change

```text
  KEY...            tickets to open (<ticketsDir>/<KEY>/ticket.md)
```

to

```text
  KEY...            tickets to open (<ticketsDir>/<KEY>/ticket.md, or a Jira key when "tracker" is configured)
  --all             every ticket.md without a run (never queries the tracker)
```

Match the wording of the existing `--all` line if there is one; edit it rather than adding a second line.

## Steps

- [ ] **1.** Edit. If a test asserts the usage text, update it in the same task (the expectation changes because the text changes).
- [ ] **2.** Package checks:

  ```bash
  uv run pytest
  uv run ruff check .
  claude plugin validate .
  ```

- [ ] **3. Commit J2** (stage by name: `ticket_project.py`, `launcher.py`, `cli.py`, `test_launch_units.py`, `test_launch_cli.py`): `Jira tracker J2: launcher accepts tracker config`.

## Done when

- J2 is one commit, and the checks are green.
