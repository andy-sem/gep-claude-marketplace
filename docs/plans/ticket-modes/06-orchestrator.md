# Task 06: orchestrator `/ticket` runs the modes

Plan: [../ticket-modes.md](../ticket-modes.md) §3 (items 1–11), D1–D4, §9.
Depends on: 04, 05. Status: not started.

## Goal

`skills/ticket/SKILL.md` decides the mode at kickoff, runs the stage set of
the mode, applies raises, and shows the mode in status, H2 and the PR.

## Read first

- `skills/ticket/SKILL.md` (all sections), `references/modes.md`,
  `references/pipeline-spec.md`, `references/config.md`

## Changes (by SKILL.md section)

1. Intro: point to `references/modes.md` (column or paragraph).
2. §0: defaults for `mode`, `modes`, `modeRules`; validate as in task 01.
3. §1: flag `--mode heavy|medium|light`, new runs only; with `--resume` the
   recorded mode is used and a differing `--mode` is refused with a message.
4. §3: new step after the ticket file: **Mode** (D1/D2). Step 6 writes
   `mode`, `modeReason`, `modeHistory: []`. After step 6: the D4 question
   when the running session model is weaker than the mode's
   (restart on the stronger model, recommended, printing
   `claude --model <model> "/ticket <KEY> --resume"` and ending the turn;
   or continue, recorded in `state.decisions` and `state.warnings`).
   Step 10: spec stage in heavy, plan stage otherwise.
5. §4 prompt: line `MODE_PIPELINE=<mode>` for planner, dev, reviewer.
6. §6 (H2): read `## Mode` of `plan.md`, apply D3 (raise to heavy before
   H2 = run spec, then plan again; light → medium = add review). H2 shows
   mode and reason; free text may raise it. Raising past the session's
   model asks the D4 question again.
7. §7/§8: after dev, a light run whose diff touches `riskPaths` is raised to
   medium and reviewed on `models.reviewRisk`; otherwise light skips §8 and
   goes to §9a.
8. §9b: light runs `fix-pr` and the verification, no reviewer; the summary
   comment says so.
9. §9a: PR body `Mode: <mode> (<reason>)` under `## Summary`; light adds
   "No review stage ran" under `## Skipped checks`.
10. §2 (status): print `mode`, `modeReason`, `modeHistory`.
11. §9 (resume): re-enter with the recorded mode.

If dev tiers has already landed: the mode bounds the tier (heavy → at least
`workhorse`, light → at most `workhorse`), see plan §9 and dev-tiers D3.4.

## Tests

None (Markdown). Read the whole skill once more for H-point numbering and
cross references.

## Done when

Every item of plan §3 is in SKILL.md; H2 is a stop in all three modes.
