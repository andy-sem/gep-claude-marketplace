# Task 04: pipeline spec for dev tiers

Plan: [../dev-tiers.md](../dev-tiers.md) D3, D4, §3 (References).
Depends on: 02. Status: not started.

## Changes

`skills/ticket/references/pipeline-spec.md`:

1. Dev row of the stage table: the three agents and how the tier is chosen
   (D3 rules, per-stage table: implement, fix-review round 1, round 2+ one
   tier up, fix-pr per round).
2. Promotion table (D4): `tier too low` → next tier, no H-point;
   `verification failed` from pawn/workhorse → next tier, continuing from
   the `Plan-Step:` trailers; second failure or godzilla failure → H6;
   other `NEEDS_DECISION` → H3; crash → single retry same tier, then H7;
   godzilla `tier too low` → H3.
3. H6 row: only after the top tier.
4. State example: `devTier`, `devTierReason`, `devTierHistory`
   (`{from, to, reason, stage, at}`); promotions also in `state.warnings`
   with `stage: "dev-tier"`, not under "Skipped checks" in the PR.

## Tests

None (Markdown).

## Done when

pipeline-spec matches plan D3/D4 and names no `ticket-dev`.
