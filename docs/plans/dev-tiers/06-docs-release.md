# Task 06: README, CLAUDE.md, versions, manual check

Plan: [../dev-tiers.md](../dev-tiers.md) §3 (References and docs), §5, §7.
Depends on: 01–05. Status: not started.

## Changes

1. Plugin README: agents table with the three tiers, configuration
   (`devTier`, tier models, `models.dev` removed), entry in "Design
   decisions and history" (decisions of 2026-11-22 included).
2. CLAUDE.md: "four stage agents" → spec, planner, three dev tiers,
   reviewer; update the `agents/` line.
3. `plugin.json` and catalog entry: version 0.14.0 (0.13.0 if this ships
   before ticket modes), description mentions dev tiers; bump
   `metadata.version`.
4. Open question O1 (tier per plan step) stays out of this version; note it
   in the README history.

## Manual check (private demo repo)

- one-line docs ticket → `pawn`;
- normal feature → `workhorse`;
- ticket with a decided schema change → `godzilla`;
- pawn forced onto a step that needs a choice → `tier too low`, automatic
  workhorse re-run;
- verification failure on workhorse → godzilla re-run, then H6;
- PR feedback round with only wording changes → `pawn`;
- confirm Pawn on haiku keeps the contract (trailers, report, escalation);
  if not, tighten "Your level" first, not the model.

## Done when

`claude plugin validate .`, `jq . .claude-plugin/marketplace.json`,
`uv run pytest`, `uv run ruff check .` green; manual check noted in the PR.
