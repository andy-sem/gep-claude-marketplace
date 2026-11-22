# Task 05: stage agents read the mode and the criteria

Plan: [../ticket-modes.md](../ticket-modes.md) D3 (planner line), D6, §4.
Depends on: 04. Status: done.

## Goal

The planner works without `spec.md`, writes the acceptance criteria and a
`## Mode` line; dev and reviewer find the criteria in either file.

## Read first

- `agents/ticket-planner.md`, `agents/ticket-dev.md`,
  `agents/ticket-reviewer.md` (contract sections and inputs)
- `skills/ticket/references/modes.md` (task 04)

## Changes

| Agent | Change |
| --- | --- |
| `ticket-planner` | Contract gets `MODE_PIPELINE=heavy|medium|light`. Without `spec.md` read `ticket.md` and write `## Acceptance criteria` (testable, from the ticket; missing or unclear → `NEEDS_DECISION` with `stage: plan`). Always write `## Mode`: `keep` or `raise to <mode>: <reason>`. |
| `ticket-dev` | Acceptance criteria from `spec.md`, else `plan.md`. Accept `MODE_PIPELINE=` (no behaviour change). |
| `ticket-reviewer` | Same as dev. |
| `ticket-spec` | Unchanged. |

`MODE_PIPELINE` is named differently from the dev agent's `MODE=` on purpose;
say so in the dev agent's contract.

If dev tiers ([../dev-tiers.md](../dev-tiers.md)) has already landed, apply
the dev change to all three dev agents (`ticket-dev-*`), keeping their
bodies identical (`test_dev_agents.py`).

## Tests

None for Markdown; `test_no_named_mcp.py` (and `test_dev_agents.py` if
present) stay green.

## Done when

All three agents handle both layouts (`spec.md` present or not).
