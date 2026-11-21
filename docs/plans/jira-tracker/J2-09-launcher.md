# Task 09: `scripts/gated_dev/launch/launcher.py`

Package **J2** · prev [Task 08](J2-08-test-launch-cli.md) · next [Task 10](J2-10-launch-cli.md) · [index](README.md)

## Goal

With a tracker, the launcher opens a session for a key that has no `ticket.md` yet. The session's tracker intake writes it.

## Change

In `TicketLauncher.launch_ticket`, the block at line ~136:

```python
if config["orchestratorRules"] and not (Path(root) / config["ticketsDir"] / key / "ticket.md").exists():
```

becomes a check of either source, with a note per source:

```python
if not (Path(root) / config["ticketsDir"] / key / "ticket.md").exists():
    if config["tracker"]:
        note = "no ticket.md yet; the session fetches it from Jira"
    elif config["orchestratorRules"]:
        note = "no ticket.md yet; the session's intake rules write it"
    else:
        note = None
    if note:
        return open_session({"mode": "main-checkout", "cwd": root, "args": [], "summary": None, "note": note})
```

When neither is set, `read_ticket` raises its existing "no ticket file" error, as before. Update the comment above the block.

The tab title is the plain `<KEY>` (`summary: None`), as for rules intake. The launcher sets `TICKET_FLOW_KEY`, so the session prints no `/rename` hint (SKILL.md §3 step 8). Leave that as it is; the README notes the plain title.

## Steps

- [ ] **1.** Make the change.
- [ ] **2.** `uv run pytest plugins/gated-dev-simple-workflow`: all of Task 06 and Task 08 pass.

## Done when

- Every test of the plugin is green, and the old message for a missing `ticket.md` without a tracker or rules is unchanged.
