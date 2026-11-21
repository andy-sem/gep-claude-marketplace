# gated-dev-simple-workflow

`/ticket <KEY>` runs one ticket through **spec → plan → dev → review → PR**,
one subagent per stage, in its own git worktree. The pipeline is file-based:
by default the ticket is a Markdown file (`docs/tickets/<KEY>/ticket.md`), and
every stage reads and writes files next to it. A project can **switch to Jira
issues** instead (see [Jira](#jira)); the stages still work on files.

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
  "formatCommand": "prettier --write",
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
`ticket.md` yet: the rules may write it), `started`, `resumed`, `spec-done`,
`plan-approved`, `dev-done`, `review-done`, `pr-body`, `pr-opened`,
`pr-feedback-addressed`, `merged`, `aborted`. One `## <event>` section per
event:

```markdown
Team notifications go through the chat tool; use its MCP tools.

## plan-approved
Add a line for this ticket to CHANGELOG.md under "Unreleased".

## pr-opened
Post the PR link to the team channel with `mcp__chat__send_message`.

## merged
Post "<KEY> merged" to the team channel with `mcp__chat__send_message`.
```

Steps only add to the pipeline: they cannot skip a stop point, change what
the stage agents get, or widen what the approved plan allows. A failing step
is recorded as a warning and the run goes on (except at `intake`). With a
[tracker](#jira), the rules run after the tracker step at each event and may
not define `intake`. Details: `skills/ticket/SKILL.md` section 0a.

## Jira

Off by default. Without `tracker` nothing in this section applies: `ticket.md`
is the ticket and no Jira call is ever made.

**Requirement:** a Jira MCP server or connector in the Claude Code session,
with rights to read issues, list and apply transitions, comment and assign
(and to read the current user). No API tokens and no client of its own.
Without these tools, kickoff stops before creating anything.

Minimal config in `.claude/gated-dev.json`:

```json
{ "tracker": { "type": "jira", "site": "acme.example.net" } }
```

`/ticket PROJ-1` then fetches the issue (summary, description, type, status,
parent, links, the last human comments) and writes it to `ticket.md`. The key
pattern defaults to `^[A-Z][A-Z0-9]*-\d+$`.

| When | Status moves | Only if the status is |
| --- | --- | --- |
| Kickoff | To Do to In Progress | in `startFrom` (default: any To Do category status) |
| PR opened or reused | In Progress to In Review | In Progress (or a `startFrom` status) |
| PR merged | to Done | not already Done |

The pipeline never moves an issue backwards and makes no other status change
(no change on abort, restart, PR feedback rounds or resume).

What lands in Jira: the issue is assigned to you at kickoff (`"assign": false`
turns that off), and a short `Pipeline:` comment (Done / Next / Blockers) is
posted at each stage transition, with the PR link when it opens. Set
`"comments": false` to post none; status changes happen either way.

Customise in the `tracker` object:

- `statuses`: target names, `{"inProgress": "In Progress", "inReview": "In
  Review", "done": "Done"}` by default. `"inReview": null` skips that step for
  workflows without In Review.
- `startFrom`: statuses kickoff may move to In Progress.
- `site`: needed only when the tools reach several Jira sites.
- `baseFromParent`: a branch glob such as `feature/{parent}/*`. If the issue
  has a parent and exactly one matching branch exists on `origin`, it becomes
  the base; none means the normal base rules; several ask you.

A failed Jira call after kickoff is a warning, not a stop: `/ticket KEY
--status` lists it and the run goes on. Kickoff stops only when the issue
cannot be read or the session has no Jira tools.

The stage agents never touch Jira and read only `ticket.md`, which is
generated from the issue and committed with the spec and plan. Every key and
the file format: `skills/ticket/references/config.md`; behaviour:
`skills/ticket/references/jira.md`.

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
| New Jira key without `ticket.md` (`tracker` set) | The main checkout, titled with the plain key; the session fetches the issue and writes `ticket.md`, then creates its worktree |
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

## Design decisions and history

This section replaces the finished plan files that used to sit in
`docs/plans/`. Git history keeps the full text.

### Origin and binding decisions

The `/ticket` pipeline (skill, four stage agents, launcher, PR watcher)
started inside a private project and was generalised into this plugin.
Decisions made with the user while porting it:

- **Workflow and gates are separate.** The pipeline knows nothing about gate
  internals. It runs the same with or without `destructive-guard` and treats
  any gate prompt or denial as a checkpoint (`NEEDS_DECISION`), never as
  something to work around. Its only coupling is a contract: when the gate's
  `check` skill is installed, the planner dry-runs its calls through it.
  Otherwise it writes `Rule ID: unknown`. No path into the other plugin is
  hard-coded.
- **Files by default, Jira optional.** The ticket is
  `<ticketsDir>/<KEY>/ticket.md`, and the key is free-form. The first port
  ruled out any tracker (2026-11-19). That was reversed on 2026-11-21: with
  `tracker` in `.claude/gated-dev.json`, the orchestrator fetches the issue
  into `ticket.md` and moves it through its statuses using the session's own
  Jira tools. The stage agents stay tracker-free either way. Other tracker
  steps go into `orchestratorRules` (one section per pipeline event).
- **Orca and iTerm2 are supported**, as well as plain `git worktree`. The
  skill detects the host and adopts a linked worktree it was opened in. The
  launcher opens one session per ticket.
- **Plan approval is always a stop point.** After it, the run commits,
  pushes, opens a PR with `gh` and watches it. New feedback starts a
  follow-up round; a merge sends a notification and removes the worktree
  (the branch is kept).
- **Public repo hygiene:** no source-project names, ticket keys or branch
  names, and neutral placeholders (`PROJ-1`, `apps/web`).

### What was checked end to end

The pipeline was run in a private demo repo: by hand, through the launcher
in Orca and in iTerm2, headless (`claude -p '/gated-dev-simple-workflow:ticket <KEY>'`,
`--continue` to answer a stop point), `--status`, interrupt plus `--resume`,
gated rows with real rule IDs, the `unknown` path without the gate, spec
questions, a denial treated as a checkpoint, and a full PR feedback round
through to merge and cleanup. Findings worth knowing:

- The plugin cache is a copy. After changing the plugin, run
  `claude plugin update gated-dev-simple-workflow@gep-claude-marketplace` in
  the project before the next run.
- The launcher reads `.claude/gated-dev.json` from the main checkout, while
  a session in a worktree reads the base branch's copy. They can differ, and
  the session reports it.
- A `Bash(git push:*)` deny in Claude Code settings doesn't match
  `git -C <worktree> push`.
- The watcher exits `0` for feedback, merged or closed, `1` on error and
  `2` on usage errors. Distinct non-zero codes per outcome made Claude Code
  report a merge as a failure.

### Python port (0.9, November 2026)

The launcher, the PR watcher and the notification hook were rewritten in
Python (>= 3.14, standard library only), and the repo contains no
JavaScript. `hooks/notify.py` starts through `hooks/run-python.sh`, which
uses the same interpreter lookup as the gate (`GATE_INFRA_PYTHON`, then
`python3.14`, then `python3`, always with `-I`). Unlike the gate,
notifications are best-effort: with no suitable Python the hook stays
silent. `jq` is no longer needed. `tests/PORTING.md` maps every old test to
its Python replacement. An installed `destructive-guard` older than its
Python version has no `lib/check.py`, so the planner writes `unknown` rule
IDs.

### Class refactor (November 2026)

One class per file, with no change in behaviour:
- `gated_dev/launch/`: naming, terminal commands, ticket project, Orca
  worktrees, launcher, CLI;
- `gated_dev/watch/`: PR client, feedback detector, watcher, CLI;
- `notify.py`, `process.py` and `errors.py`.

### Planned change in the gate

If `destructive-guard` moves to the Jev-only design in
`docs/plans/lean-gate.md`, it has no rule ids any more. The planner's
`## Gated operations` table would then need another source (decision D6
there).

## Requirements

`git`, and `gh` (authenticated) for the PR; `orca` when running in Orca; **Python >= 3.14** (standard library only) for the launcher, the PR watcher and the notification hook (`python3`, or `GATE_INFRA_PYTHON` when `python3` is older; install with `brew install python@3.14`, `uv python install 3.14` or from python.org); optional `notify-send` (Linux) for notifications (silent without Python).

## Install

```text
/plugin marketplace add gep/gep-claude-marketplace
/plugin install gated-dev-simple-workflow@gep-claude-marketplace
```
