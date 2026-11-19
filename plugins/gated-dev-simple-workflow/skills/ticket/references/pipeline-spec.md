# Ticket pipeline: design

## 1. Goal

A developer types `/ticket <KEY>` (or "start working on ticket <KEY>"). The
ticket then runs through **kickoff → spec → plan → dev → review → complete**,
each stage in its own subagent, in its own git worktree. The pipeline works on
its own and stops for the developer only at the points in §3.

## 2. Principles

| Principle | Meaning |
| --- | --- |
| Files, not trackers | The ticket is `ticket.md`; context passes between stages only through files in the ticket directory and the recorded decisions. |
| Plan approval always required | No product code is written and no gated action is attempted before the developer approves the plan (H2). |
| Important decisions always escalated | At any stage, including after the plan is approved (§4). |
| Gates are separate | Approval gates are enforced by a `PreToolUse` hook (for example the `destructive-guard` plugin), not by prompt text. The pipeline treats a gate prompt or denial as a checkpoint and never works around it. It runs the same with or without a gate. |
| One ticket per session | Parallel tickets run in separate sessions, each in its own worktree. |

## 3. Human interaction points

The **only** places the pipeline stops. Every stop is an `AskUserQuestion`
from the orchestrator, recommended option first, except H4.

| # | When | Shown | Options |
| --- | --- | --- | --- |
| H1 | Spec stage finds a blocking question | Question, context, recommendation | An option or free text |
| H2 | **Plan ready (mandatory)** | Plan summary, path to `plan.md`, the gated operations table, open decisions | Approve · Request changes (free text, then re-plan) · Abort |
| H3 | Any stage raises `NEEDS_DECISION` (§4) | Question, options, trade-offs, recommendation | An option or free text |
| H4 | A gated tool call | The permission prompt with the exact call and the gate's reason | Allow · Deny |
| H5 | Review loop limit (2 fix rounds) with critical or important findings open | Remaining findings | Accept as is · One more round · Take over manually |
| H6 | Verification still fails after 2 dev fix attempts, or an infrastructure blocker | Failing command and output excerpt | Retry · Skip this check (listed in the PR) · Abort |
| H7 | Subagent failure (crash, empty result, missing file) after 1 automatic retry, or a scope-check failure | Error summary | Retry · Abort |

Approving the plan also authorises the run's normal actions afterwards: local
commits, pushing the ticket branch and opening the PR. Force pushes and pushes
to other branches are never done. Rejecting the plan sends the feedback to the
planner and H2 is asked again, without a round limit.

## 4. Important decisions and `NEEDS_DECISION`

A subagent must escalate instead of choosing when a decision changes scope or
acceptance criteria, departs from the approved plan in more than a trivial
way, touches the data model or schema, security, auth, tenant isolation or
secrets, adds a dependency, service, cloud resource or recurring cost, picks
between approaches with long-term trade-offs, would leave the work partly
done, or matches a project rule (`escalationExtra`). Not escalated: naming,
file placement that follows conventions, test structure, local refactors,
fixes for review findings within the plan. When unsure, escalate.

Subagents cannot ask the developer. They save their work (commit it or write
their stage file) and end with:

```
NEEDS_DECISION
stage: spec|plan|dev|review
question: <one sentence>
context: <at most 5 lines>
options:
  - label: <short> | <consequence>
  - label: <short> | <consequence>
recommendation: <label> - <why>
```

The orchestrator asks H1/H3, records the answer in `state.json` and
`decisions.md`, and runs the same stage again with the answer under
`DECISIONS:`. Output with both a result and this block counts as needing a
decision. A dev question starting with `verification failed: ` is H6.

## 5. Stages

Every file lives in `<ticketsDir>/<KEY>/` in the ticket worktree.

| Stage | Who | Reads | Writes | Exit |
| --- | --- | --- | --- | --- |
| kickoff | orchestrator | `ticket.md`, config | worktree, `state.json`, `decisions.md` | worktree exists, setup ran |
| spec | spec agent (read-only) | `ticket.md`, repo docs, code | `spec.md` (goal, context, in/out of scope, testable acceptance criteria, assumptions, open questions tagged blocking/non-blocking) | no blocking questions left |
| plan | planner (read-only) | `spec.md`, `decisions.md`, repo | `plan.md` (steps with files and checks, gated operations table, verification, risks) | **H2 approval**; then `ticket.md`, `spec.md`, `plan.md`, `decisions.md` are committed |
| dev | dev agent (all tools) | `plan.md`, `spec.md`, `decisions.md` | one commit per step (`Plan-Step: N`), `dev-report.md` | steps done, verification passes (2 fix attempts, then H6) |
| review | reviewer (read-only) | diff vs base, `spec.md`, `plan.md`, `dev-report.md` | `review.md`: critical / important / minor findings, `VERDICT: PASS|CHANGES_REQUIRED` | PASS, or H5 after 2 fix rounds |
| complete | orchestrator | `plan.md`, `review.md`, `state.json` | push, PR | PR open, stage `done` |

Read-only stages may change only the ticket directory; the orchestrator checks
`git status --porcelain` after them (scope check → H7). Review fix rounds run
the dev agent with `MODE=fix-review` (critical and important only, commits
with `Review-Fix: <n>`). Minor findings go into the PR. The reviewer runs on a
stronger model when the diff touches `riskPaths`.

## 6. Hosts

| Host | Detected by | Worktree created with | Removed with |
| --- | --- | --- | --- |
| Orca | `TERM_PROGRAM=Orca`, or `ORCA_TERMINAL_HANDLE` without `TERM_PROGRAM=iTerm.app` | `orca worktree create ... --json` | `orca worktree rm` |
| iTerm2 | `TERM_PROGRAM=iTerm.app` or `ITERM_SESSION_ID` | `git worktree add --no-track -b` | `git worktree remove` |
| other | anything else | `git worktree add --no-track -b` | `git worktree remove` |

A session that already runs in a linked worktree (opened by a launcher or by
Orca) adopts it instead of creating one, when its branch is the ticket's or is
clean, unused and behind the base. Sessions started by hand get a `/rename`
hint; launched sessions carry `TICKET_FLOW_KEY` and are already named.

## 7. State and resume

`state.json` (ignored through `.git/info/exclude`, never committed):

```json
{
  "ticket": "PROJ-1",
  "title": "Export reports as CSV",
  "baseBranch": "main",
  "baseRef": "origin/main",
  "branch": "PROJ-1/export-reports-as-csv",
  "worktree": "/abs/repo/.claude/worktrees/proj-1-export-reports-as-csv",
  "host": "orca | iterm | plain",
  "stage": "spec | plan | awaiting_plan_approval | dev | review | complete | done | aborted",
  "abortedFrom": "dev",
  "reviewRound": 0,
  "decisions": [{ "stage": "plan", "question": "...", "answer": "...", "at": "ISO-8601" }],
  "warnings": [{ "stage": "dev", "command": "...", "reason": "...", "at": "ISO-8601" }],
  "prUrl": null,
  "updatedAt": "ISO-8601"
}
```

`--resume` re-enters the recorded stage from its start. Stages are safe to run
again: they overwrite their own file, and dev skips steps whose `Plan-Step: N`
commit already exists. Abort keeps the worktree and branch.

## 8. Not in this version

- PR follow-up: watching the PR, addressing review comments
  (`--address-review`, dev `MODE=fix-pr`), merge cleanup.
- Notifications.
- A launcher that opens one session per ticket in Orca or iTerm2 tabs.
- Running without a developer present, or in CI.
