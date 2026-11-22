# Dev tiers: tasks

Tasks for [../dev-tiers.md](../dev-tiers.md) (Godzilla, Workhorse, Pawn dev
agents). The plan stays the source of the decisions (D1–D5); each task names
the sections it implements. One task is one work package and one commit
(CLAUDE.md). Work on a feature branch; do not push unless asked.

| # | Task | Depends on |
| --- | --- | --- |
| 01 | [Config: `devTier`, tier models, `models.dev` error](01-config.md) | – |
| 02 | [Three dev agents replace `ticket-dev`](02-dev-agents.md) | – |
| 03 | [Planner writes `## Dev tier`](03-planner-tier.md) | – |
| 04 | [References: pipeline spec](04-references.md) | 02 |
| 05 | [Orchestrator: choice, promotion, fix rounds](05-orchestrator.md) | 01–04 |
| 06 | [README, CLAUDE.md, versions, manual check](06-docs-release.md) | all |

01–03 can run in parallel. Task 02 removes `ticket-dev`, which the
orchestrator still names until task 05: land 02 and 05 on the same branch
and release nothing in between.

Binding for every task: one dev contract for all tiers (D1); every tier
escalates the full escalation list; plan approval (H2) unchanged; Pawn runs
on `haiku`; promotion is automatic all the way up for `tier too low` and
`verification failed`, in every dev mode (decided 2026-11-22); public repo
hygiene.
