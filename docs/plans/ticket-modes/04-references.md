# Task 04: references `modes.md` and pipeline spec

Plan: [../ticket-modes.md](../ticket-modes.md) §1, D1–D4, D6, §6.
Depends on: –. Status: done.

## Goal

The rules the orchestrator, planner and flow driver follow are written down
once, in the references the skills already point to.

## Read first

- `skills/ticket/references/pipeline-spec.md` (stage table, H-points, §4
  escalation, §7 state example)
- `skills/ticket/references/flow.md`

## Changes

1. New `skills/ticket/references/modes.md`:
   - the mode table (stages, session model, meant for);
   - what never changes (H2 in every mode, escalation, gate, H6/H7, PR);
   - D1 (decided once at kickoff, recorded, not asked);
   - D2 decision rules in order, "when unsure take the heavier one";
   - D3 raise table (raise only, never lower; recorded in
     `state.decisions`, `decisions.md` with `stage: mode`, `modeHistory`);
   - D4 session model: launched sessions vs. hand-started; the restart /
     continue question and the exact resume command it prints;
   - D6 acceptance criteria in `plan.md` without a spec;
   - light mode gets no review because of gated operations, only via
     `riskPaths` in the diff or an explicit raise (decided 2026-11-22).
2. `pipeline-spec.md`:
   - stage table per mode;
   - H1 role taken over by the planner's `NEEDS_DECISION` (stage `plan`) in
     medium and light;
   - H2 row mentions the mode and that the developer may raise it;
   - §7 state example gets `mode`, `modeReason`, `modeHistory`.

## Tests

None (Markdown). Check `test_no_named_mcp.py` still passes.

## Done when

`modes.md` exists and covers D1–D4, D6; pipeline-spec is consistent with it.
