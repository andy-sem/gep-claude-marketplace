# gated-dev-simple-workflow

Work in progress. See `docs/plans/gated-dev-simple-workflow.md` at the
repository root for the porting plan and work packages.

The pipeline is file-based: the ticket is a Markdown file
(`<ticketsDir>/<KEY>/ticket.md`, default `docs/tickets/<KEY>/ticket.md`),
and every stage reads and writes files next to it. No issue tracker is used.

## Agents

| Agent | Stage | Writes |
| --- | --- | --- |
| `gated-dev-simple-workflow:ticket-spec` | 1. spec | `spec.md` |
| `gated-dev-simple-workflow:ticket-planner` | 2. plan | `plan.md` |
| `gated-dev-simple-workflow:ticket-dev` | 3. implement / fix | commits + `dev-report.md` |
| `gated-dev-simple-workflow:ticket-reviewer` | 4. review | `review.md` |

They are started by the `ticket` skill (coming in WP-W2), not directly. Each
ends with `RESULT: OK <file>` or a `NEEDS_DECISION` block. A prompt or denial
from an approval gate (for example the `destructive-guard` plugin) is treated
as a checkpoint, never worked around.

## Install

```text
/plugin install gated-dev-simple-workflow --marketplace gep/gep-claude-marketplace
```
