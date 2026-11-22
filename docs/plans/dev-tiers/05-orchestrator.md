# Task 05: orchestrator chooses and promotes the tier

Plan: [../dev-tiers.md](../dev-tiers.md) D3, D4, D5, §3 (Orchestrator 1–9).
Depends on: 01–04. Status: not started.

## Goal

`skills/ticket/SKILL.md` runs the dev stage on the chosen tier, promotes it
automatically, and shows the tier in status, H2 and the PR.

## Changes (by SKILL.md section)

1. Intro table: dev row lists the three agents.
2. §0: defaults for `devTier` and the three model keys; the `models.dev`
   error.
3. §4: for dev, `subagent_type` is the agent of the chosen tier and `model`
   the tier's key (passed explicitly). Parse step: `tier too low:` (D4).
4. §6 (H2): read `## Dev tier`; decide by D3.2 (config `devTier` → tier
   named in the H2 free text → never `pawn` with gated operations,
   `riskPaths` or a risk step → planner's tier → `workhorse`); show it in the
   H2 summary; write `devTier`, `devTierReason`. No extra question.
5. §7: implement on `devTier`; promotion per D4; H6 only after the top tier.
6. §8: fix-review round 1 on `devTier`, round 2+ one tier up.
7. §9b step 6: fix-pr tier per round from `pr-feedback-<n>.md` (pawn when
   every `change` item is mechanical, else `devTier`, at least `workhorse`
   when an item touches `riskPaths`); promotion applies.
8. §2 (status): print `devTier`, `devTierHistory`.
9. §9a: PR body `## Summary` names the tier(s) that wrote the code.
10. Replace every remaining `ticket-dev` reference.

If ticket modes has landed: the mode bounds the tier (heavy → at least
`workhorse`, light → at most `workhorse`), D3.4.

## Tests

None (Markdown). `grep -rn "ticket-dev\b" plugins/` finds only the new
agent names.

## Done when

Every item of plan §3 "Orchestrator" is in SKILL.md.
