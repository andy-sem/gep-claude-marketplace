# Task 03: planner writes `## Dev tier`

Plan: [../dev-tiers.md](../dev-tiers.md) D3.1, §3 (Agents 4).
Depends on: –. Status: not started.

## Goal

`plan.md` carries the planner's advice on which dev tier should implement it.

## Changes

`agents/ticket-planner.md`: new required section `## Dev tier` in `plan.md`:
one of `godzilla | workhorse | pawn` and a one-line reason (step count, how
much each step leaves open, risk, files touched). Criteria from the table
in plan §1:

- `pawn`: few, mechanical steps fully spelled out (copy, config, docs,
  renames, a test for a known case); never when the plan has gated
  operations, touches `riskPaths`, or marks a step as a risk;
- `workhorse`: the normal case;
- `godzilla`: many steps, cross-cutting, tricky logic, migrations,
  concurrency, performance, decided escalation items.

If ticket modes has landed: light → at most `workhorse`; needing
`godzilla` on a light ticket means `## Mode` raises the mode instead.

## Tests

None (Markdown); `test_no_named_mcp.py` stays green.

## Done when

The planner's output format lists `## Dev tier` with the criteria.
