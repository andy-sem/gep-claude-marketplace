# Ticket modes: tasks

Tasks for [../ticket-modes.md](../ticket-modes.md) (heavy, medium, light
pipeline modes). The plan stays the source of the decisions (D1–D6); each
task names the sections it implements. One task is one work package and one
commit (CLAUDE.md). Work on a feature branch; do not push unless asked.

| # | Task | Depends on |
| --- | --- | --- |
| 01 | [Config keys and validation](01-config.md) | – |
| 02 | [Launcher: session model and `--mode`](02-launcher-model.md) | 01 |
| 03 | [Flow CLI: `launch --mode` and status](03-flow-cli-mode.md) | 02 |
| 04 | [References: `modes.md`, pipeline spec](04-references.md) | – |
| 05 | [Stage agents: acceptance criteria and `## Mode`](05-stage-agents.md) | 04 |
| 06 | [Orchestrator `/ticket`](06-orchestrator.md) | 04, 05 |
| 07 | [`/ticket-flow` decides and passes the mode](07-ticket-flow.md) | 03, 06 |
| 08 | [README, versions, manual check](08-docs-release.md) | all |

01–03 (Python, tested) and 04–06 (Markdown) are two independent chains. Tasks
02, 03 and 07 must not ship without 06: a launched session would get a
`--mode` flag the orchestrator does not know yet. Release only after 08.

Binding for every task: plan approval (H2) stays a stop point in every mode;
escalation list, gate handling, H6/H7, commit/push/PR/watch unchanged; stage
agents stay tracker-free; public repo hygiene (neutral names, no named MCP
servers).
