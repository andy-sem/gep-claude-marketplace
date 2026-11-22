# Task 02: three dev agents replace `ticket-dev`

Plan: [../dev-tiers.md](../dev-tiers.md) §1, D1, D2, D4 (prefix), §3 (Agents 1–3), §4.
Depends on: –. Status: not started.

## Goal

`ticket-dev-godzilla`, `ticket-dev-workhorse`, `ticket-dev-pawn` exist with
one shared body, and a test keeps them from drifting.

## Read first

- `plugins/gated-dev-simple-workflow/agents/ticket-dev.md` (whole contract)
- `tests/test_no_named_mcp.py` (scans every `*.md` outside `tests/`, so the
  new files are covered without changes)

## Changes

1. `git mv agents/ticket-dev.md agents/ticket-dev-workhorse.md`; new
   `name`, `description`, `model: sonnet`, `effort: high`; add a
   "Your level" section (as `ticket-dev` today).
2. New `ticket-dev-godzilla.md` (`opus`, `high`): may restructure within the
   planned files and pick the approach when the plan leaves it open; still
   escalates everything on the escalation list.
3. New `ticket-dev-pawn.md` (`haiku`, `medium`): follows the plan literally;
   a step that needs a choice the plan does not make, an unlisted file, or
   more than a local change ends with `NEEDS_DECISION` whose `question:`
   starts with `tier too low: `. Description: mechanical steps only.
4. All three, "Final line": document `tier too low: ` next to
   `verification failed: `.
5. Bodies identical outside frontmatter and "Your level".
6. If ticket modes task 05 has landed, the `MODE_PIPELINE=` and acceptance
   criteria lines are already in the body; keep them.

## Tests

New `tests/test_dev_agents.py`:

- the three files exist, `ticket-dev.md` is gone;
- frontmatter `name`, `model`, `effort` as in plan §1;
- bodies identical once frontmatter and the "Your level" section are cut;
- each mentions both prefixes `tier too low: ` and `verification failed: `.

## Done when

Tests green. The orchestrator still names `ticket-dev` until task 05; do not
release in between.
