# gated-dev-simple-workflow

`/ticket <KEY>` runs one ticket through **spec → plan → dev → review → PR**,
one subagent per stage, in its own git worktree. The pipeline is file-based:
the ticket is a Markdown file (`docs/tickets/<KEY>/ticket.md` by default),
and every stage reads and writes files next to it. The pipeline uses no issue
tracker itself; a project can connect one with its own
[project rules](#project-rules).

## Usage

```text
/ticket PROJ-1                       # ticket.md must exist, or paste a description:
/ticket add-csv-export Users want to export reports as CSV ...
/ticket PROJ-1 --status
/ticket PROJ-1 --resume
/ticket PROJ-1 --address-review      # address new PR feedback now
```

The run stops for you only at fixed points: blocking spec questions,
**plan approval (always)**, important decisions an agent escalates,
verification failures, review-loop limits and agent failures. After the plan
is approved it commits, pushes the ticket branch and opens a PR with `gh`.

### After the PR is open

The session keeps watching the PR (`scripts/watch_pr.py` in the background,
one `gh` poll a minute):

- **New review feedback** from a person (bots and the pipeline's own replies
  are ignored) starts a follow-up round: each item is classified as change,
  question or decline in `pr-feedback-<n>.md` (you confirm every decline and
  decide anything ambiguous or out of scope), the dev agent fixes the changes
  (`PR-Fix: <comment id>` commits), the reviewer checks them, the branch is
  pushed and every item gets a reply marked `<!-- gated-dev -->`. Threads stay
  unresolved and no review is re-requested; that is up to you.
- **Merged**: you get a notification and the worktree is removed when it is
  clean and at the merged commit. The branch is kept.
- **Closed** without a merge: the watch stops; nothing else changes.

Closing the session stops the watch; `/ticket <KEY> --resume` (or the
launcher) restarts it, and catches up on a merge that happened meanwhile.

Worktrees go to `.claude/worktrees/<key>-<slug>` on branch `<KEY>/<slug>`.
In Orca they are created with `orca worktree create`; in iTerm2 and other
terminals with `git worktree add`. A session that already runs in a linked
worktree adopts it.

## Ticket files and run state

Write `docs/tickets/<KEY>/ticket.md` (the first `# ` heading is the title; it
names the branch and the PR; optional front matter `base:` picks the base
branch), or paste a description after the key and `/ticket` writes the file.
Commit it on the base branch or leave it untracked: kickoff copies it into the
ticket worktree. Every stage works on files next to it:

| File | Written by | Committed |
| --- | --- | --- |
| `ticket.md` | you / kickoff | at plan approval |
| `spec.md` | spec agent | at plan approval |
| `plan.md` | planner | at plan approval |
| `decisions.md` | orchestrator (your answers at stop points) | at plan approval, then on every append |
| `dev-report.md` | dev agent | by the dev agent |
| `review.md` | reviewer | after each review round |
| `pr-feedback-<n>.md` | orchestrator (PR follow-up round `n`) | at the start of the round |
| `state.json` | orchestrator | never (ignored through `.git/info/exclude`) |

`state.json` records the stage, which `--status` prints and `--resume`
re-enters from its start: `spec` → `plan` → `awaiting_plan_approval` → `dev`
→ `review` → `complete` → `done` ⇄ `addressing_review` → `merged` (or
`aborted`). It also holds the branch, worktree, base, review round,
decisions, warnings, the PR URL, the time of the last PR feedback handled
(`lastAddressedCommentAt`) and the watcher's heartbeat (`watch`).

## Configuration

Optional, per project, in `.claude/gated-dev.json`. Every key is optional; an
invalid file or an unknown key stops the run with a message. Example:

```json
{
  "ticketsDir": "docs/tickets",
  "keyPattern": "^[A-Z]+-\\d+$",
  "baseBranch": "develop",
  "setupCommand": "npm ci",
  "formatCommand": "npx prettier --write",
  "riskPaths": ["**/migrations/**", "src/auth/**"],
  "escalationExtra": ["any change to the public API of packages/sdk"],
  "models": { "plan": "opus", "reviewRisk": "opus" }
}
```

Regex backslashes are doubled in JSON (`\\d`, not `\d`). Every key, its
default and the ticket file format: `skills/ticket/references/config.md`.

### Project rules

`"orchestratorRules": ".claude/gated-dev-rules.md"` points to a Markdown file
with extra steps the orchestrator runs at fixed events: `intake` (no
`ticket.md` yet: the rules may write it, for example from an issue tracker),
`started`, `resumed`, `spec-done`, `plan-approved`, `dev-done`,
`review-done`, `pr-body`, `pr-opened`, `pr-feedback-addressed`, `merged`,
`aborted`. One `## <event>` section per event:

```markdown
Tickets live in the team tracker; use its MCP tools.

## intake
Fetch the ticket, its parent and linked issues and write them to ticket.md
(`# <summary>`, then the description). If the parent has a branch
`feature/<PARENT>/*` on origin, put it in the front matter as `base:`.

## started
Assign the ticket to me and move it to In Progress if it is in To Do.

## pr-opened
Comment on the ticket with the PR link.

## merged
Move the ticket to Done unless it already is.
```

Steps only add to the pipeline: they cannot skip a stop point, change what
the stage agents get, or widen what the approved plan allows. A failing step
is recorded as a warning and the run goes on (except at `intake`). Details:
`skills/ticket/SKILL.md` section 0a.

## Launching several tickets

`/gated-dev-simple-workflow:launch` (or the script directly) opens one new
Claude Code session per ticket, each running `/ticket <KEY>`, in a new Orca
or iTerm2 tab:

```bash
python3 -I <plugin>/scripts/launch.py --dry-run PROJ-1 PROJ-2   # show what would open
python3 -I <plugin>/scripts/launch.py PROJ-1 PROJ-2
python3 -I <plugin>/scripts/launch.py --all                     # every ticket.md without a run
```

| Case | Where the session starts |
| --- | --- |
| New ticket, Orca, repo registered in Orca | A new Orca worktree on `<KEY>/<slug>` (base: front matter `base:`, `baseBranch`, `origin/HEAD`, `main`), with `ticket.md` and `.claude/settings.local.json` copied in; the session adopts it |
| New ticket, iTerm2 (or a repo Orca does not know) | The main checkout; the session creates its worktree |
| New ticket without `ticket.md`, `orchestratorRules` set | The main checkout; the session's `intake` rules write the ticket, then it creates its worktree |
| Ticket with a run | Its worktree, with `/ticket <KEY> --resume` (for a finished run, `stage: done`, that restarts the PR watch) |

Sessions are named `<KEY> · <title>` (`<KEY> resume · <title>`) and get
`TICKET_FLOW_KEY`; `--remote-control` also starts them with Remote Control.
Outside Orca and iTerm2 only `--dry-run` works.

### Notifications

Launched sessions (those with `TICKET_FLOW_KEY`) show a desktop notification
titled `<KEY> needs you` whenever Claude Code raises a `Notification` event:
a permission or gate prompt, a stop point such as plan approval, or an idle
wait for input. macOS uses `osascript` (with a sound), Linux uses
`notify-send` when it is installed; other systems stay silent. The message
comes from the event (a generic text when it has none). Sessions started
by hand are never notified by the hook. While a session only watches its PR,
Claude Code's idle notice fires once too. A merge sends `<KEY> merged` from
any session. Set `GATED_DEV_NOTIFY=0` to turn all of it off. The hook needs Python >= 3.14
(`GATE_INFRA_PYTHON`, else `python3.14`, else `python3`); without it the hook
stays silent.

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

`git`, and `gh` (authenticated) for the PR; `orca` when running in Orca; **Python >= 3.14** (standard library only) for the launcher, the PR watcher and the notification hook (`python3`, or `GATE_INFRA_PYTHON` when `python3` is older; install with `brew install python@3.14`, `uv python install 3.14` or from python.org); optional `notify-send` (Linux) for notifications (silent without Python).

## Install

```text
/plugin marketplace add gep/gep-claude-marketplace
/plugin install gated-dev-simple-workflow@gep-claude-marketplace
```
