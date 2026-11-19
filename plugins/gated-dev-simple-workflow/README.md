# gated-dev-simple-workflow

Work in progress. See `docs/plans/gated-dev-simple-workflow.md` at the
repository root for the porting plan and work packages.

`/ticket <KEY>` runs one ticket through **spec → plan → dev → review → PR**,
one subagent per stage, in its own git worktree. The pipeline is file-based:
the ticket is a Markdown file (`docs/tickets/<KEY>/ticket.md` by default),
and every stage reads and writes files next to it. No issue tracker is used.

## Usage

```text
/ticket PROJ-1                       # ticket.md must exist, or paste a description:
/ticket add-csv-export Users want to export reports as CSV ...
/ticket PROJ-1 --status
/ticket PROJ-1 --resume
```

The run stops for you only at fixed points: blocking spec questions,
**plan approval (always)**, important decisions an agent escalates,
verification failures, review-loop limits and agent failures. After the plan
is approved it commits, pushes the ticket branch and opens a PR with `gh`.

Worktrees go to `.claude/worktrees/<key>-<slug>` on branch `<KEY>/<slug>`.
In Orca they are created with `orca worktree create`; in iTerm2 and other
terminals with `git worktree add`. A session that already runs in a linked
worktree adopts it.

Per-project settings (tickets directory, key pattern, base branch, setup and
format commands, risky paths, extra escalation rules, models) go in
`.claude/gated-dev.json`; see `skills/ticket/references/config.md`.

## Launching several tickets

`/gated-dev-simple-workflow:launch` (or the script directly) opens one new
Claude Code session per ticket, each running `/ticket <KEY>`, in a new Orca
or iTerm2 tab:

```bash
node <plugin>/scripts/launch.mjs --dry-run PROJ-1 PROJ-2   # show what would open
node <plugin>/scripts/launch.mjs PROJ-1 PROJ-2
node <plugin>/scripts/launch.mjs --all                     # every ticket.md without a run
```

| Case | Where the session starts |
| --- | --- |
| New ticket, Orca, repo registered in Orca | A new Orca worktree on `<KEY>/<slug>` (base: front matter `base:`, `baseBranch`, `origin/HEAD`, `main`), with `ticket.md` and `.claude/settings.local.json` copied in; the session adopts it |
| New ticket, iTerm2 (or a repo Orca does not know) | The main checkout; the session creates its worktree |
| Ticket with a run | Its worktree, with `/ticket <KEY> --resume` |
| Finished run (`stage: done`) | Skipped |

Sessions are named `<KEY> · <title>` (`<KEY> resume · <title>`) and get
`TICKET_FLOW_KEY`; `--remote-control` also starts them with Remote Control.
Outside Orca and iTerm2 only `--dry-run` works.

## Agents

| Agent | Stage | Writes |
| --- | --- | --- |
| `gated-dev-simple-workflow:ticket-spec` | 1. spec | `spec.md` |
| `gated-dev-simple-workflow:ticket-planner` | 2. plan | `plan.md` |
| `gated-dev-simple-workflow:ticket-dev` | 3. implement / fix | commits + `dev-report.md` |
| `gated-dev-simple-workflow:ticket-reviewer` | 4. review | `review.md` |

Each ends with `RESULT: OK <file>` or a `NEEDS_DECISION` block. A prompt or
denial from an approval gate (for example the `destructive-guard` plugin) is
treated as a checkpoint, never worked around.

With `destructive-guard` installed and enabled, the planner dry-runs every
call its steps need through the gate (`destructive-guard:check`) and lists
the ones that will ask, with their rule IDs, in the plan's
`## Gated operations` table; you see that table at plan approval. Without a
gate the table lists the calls it expects to need approval, with
`Rule ID: unknown`.

## Requirements

`git`, and `gh` (authenticated) for the PR; `orca` when running in Orca; `node` for the launcher.

## Install

```text
/plugin marketplace add gep/gep-claude-marketplace
/plugin install gated-dev-simple-workflow@gep-claude-marketplace
```
