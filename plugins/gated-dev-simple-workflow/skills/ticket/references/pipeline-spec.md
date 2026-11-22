# Ticket pipeline: design

## 1. Goal

A developer types `/ticket <KEY>` (or "start working on ticket <KEY>"). The
ticket then runs through **kickoff → spec → plan → dev → review → complete**,
each stage in its own subagent, in its own git worktree. After the PR is open
the session watches it: new review feedback is addressed in a follow-up round
(§5a), and a merge removes the worktree. The pipeline works on
its own and stops for the developer only at the points in §3.

How many stages a ticket runs depends on its mode, decided once at kickoff
([modes.md](modes.md)): `heavy` runs spec → plan → dev → review, `medium`
plan → dev → review, `light` plan → dev. Plan approval (H2) is a stop in
every mode.

## 2. Principles

| Principle | Meaning |
| --- | --- |
| Files between stages | The ticket is `ticket.md`; context passes between stages only through files in the ticket directory and the recorded decisions. An issue tracker (Jira, `tracker` config) is read once at kickoff into `ticket.md` and updated by the orchestrator at fixed events; stage agents never use it. |
| Project steps are additions | A project can add its own steps at fixed events (`orchestratorRules`). Tracker steps run before the project's rules at the same event. They run in the orchestrator, never in a stage agent, and cannot skip an interaction point or widen what the plan authorises. |
| Plan approval always required | No product code is written and no gated action is attempted before the developer approves the plan (H2). |
| Important decisions always escalated | At any stage, including after the plan is approved (§4). |
| Gates are separate | Approval gates are enforced by a `PreToolUse` hook (for example the `destructive-guard` plugin), not by prompt text. The pipeline treats a gate prompt or denial as a checkpoint and never works around it. It runs the same with or without a gate. |
| One ticket per session | Parallel tickets run in separate sessions, each in its own worktree. |

## 3. Human interaction points

The **only** places the pipeline stops. Every stop is an `AskUserQuestion`
from the orchestrator, recommended option first, except H4.

| # | When | Shown | Options |
| --- | --- | --- | --- |
| H1 | Spec stage finds a blocking question (heavy only; in medium and light the planner's `NEEDS_DECISION` with `stage: plan`, asked as H3, takes this role) | Question, context, recommendation | An option or free text |
| H2 | **Plan ready (mandatory, every mode)** | Plan summary, path to `plan.md`, the gated operations table, open decisions, the mode and its reason (and a raise the planner made) | Approve · Request changes (free text, then re-plan; the text may raise the mode, [modes.md §5](modes.md#5-raising-the-mode-d3)) · Abort |
| H3 | Any stage raises `NEEDS_DECISION` (§4) | Question, options, trade-offs, recommendation | An option or free text |
| H4 | A gated tool call | The permission prompt with the exact call and the gate's reason | Allow · Deny |
| H5 | Review loop limit (no review stage in light mode unless raised) (2 fix rounds) with critical or important findings open | Remaining findings | Accept as is · One more round · Take over manually |
| H6 | Verification still fails after 2 dev fix attempts on the top tier (§5b), or an infrastructure blocker | Failing command and output excerpt | Retry · Skip this check (listed in the PR) · Abort |
| H7 | Subagent failure (crash, empty result, missing file) after 1 automatic retry, or a scope-check failure | Error summary | Retry · Abort |

Approving the plan also authorises the run's normal actions afterwards: local
commits, pushing the ticket branch and opening the PR. Force pushes and pushes
to other branches are never done. Rejecting the plan sends the feedback to the
planner and H2 is asked again, without a round limit.

With a `tracker`, `/ticket <KEY>` itself authorises reading the issue,
assigning it, the three forward transitions of `jira.md` §4 and the
`Pipeline:` comments. Reading and assigning happen before H2. Nothing else in
the tracker is ever changed.

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
decision. A dev question starting with `verification failed: ` is H6 (after
promotion, §5b); one starting with `tier too low: ` promotes the dev tier.

## 5. Stages

Every file lives in `<ticketsDir>/<KEY>/` in the ticket worktree.

Stages per mode ([modes.md §1](modes.md#1-the-modes)):

| Stage | heavy | medium | light |
| --- | --- | --- | --- |
| kickoff | yes | yes | yes |
| spec | yes | no | no |
| plan | yes, from `spec.md` | yes, from `ticket.md`, writes the acceptance criteria | as medium |
| dev | yes | yes | yes |
| review | yes | yes | no, unless the mode is raised (`riskPaths` in the diff, or an explicit raise) |
| complete, done, addressing_review, merged | yes | yes | yes (addressing_review without the reviewer unless raised) |

The mode can be raised during the run, never lowered
([modes.md §5](modes.md#5-raising-the-mode-d3)).

| Stage | Who | Reads | Writes | Exit |
| --- | --- | --- | --- | --- |
| kickoff | orchestrator | `ticket.md`, config | worktree, `state.json`, `decisions.md` | worktree exists, setup ran |
| spec (heavy) | spec agent (read-only) | `ticket.md`, repo docs, code | `spec.md` (goal, context, in/out of scope, testable acceptance criteria, assumptions, open questions tagged blocking/non-blocking) | no blocking questions left |
| plan | planner (read-only) | `spec.md` (heavy) or `ticket.md` (medium, light), `decisions.md`, repo | `plan.md` (steps with files and checks, gated operations table, verification, risks, `## Mode`; in medium and light also `## Acceptance criteria`) | **H2 approval**; then `ticket.md`, `spec.md` (when it exists), `plan.md`, `decisions.md` are committed |
| dev | `ticket-dev-godzilla` / `-workhorse` / `-pawn` (all tools), tier per §5b | `plan.md`, `spec.md` (when it exists), `decisions.md` | one commit per step (`Plan-Step: N`), `dev-report.md` | steps done, verification passes (2 fix attempts, then promotion or H6) |
| review (heavy, medium) | reviewer (read-only) | diff vs base, `spec.md` (when it exists), `plan.md`, `dev-report.md` | `review.md`: critical / important / minor findings, `VERDICT: PASS|CHANGES_REQUIRED` | PASS, or H5 after 2 fix rounds |
| complete | orchestrator | `plan.md`, `review.md`, `state.json` | push, PR | PR open, stage `done` |
| done | orchestrator + `watch_pr.py` (background) | the PR | `watch` heartbeat in `state.json` | feedback → `addressing_review`, merged → `merged`, closed → stop |
| addressing_review | orchestrator, dev (`MODE=fix-pr`), reviewer (`REVIEW_SINCE`) | PR reviews and comments | `pr-feedback-<n>.md`, `PR-Fix: <id>` commits, push, replies | back to `done` |
| merged | orchestrator | the PR | notification | worktree removed (branch kept) |

Read-only stages may change only the ticket directory; the orchestrator checks
`git status --porcelain` after them (scope check → H7). Review fix rounds run
the dev agent with `MODE=fix-review` (critical and important only, commits
with `Review-Fix: <n>`; tier per §5b). Minor findings go into the PR. The reviewer runs on a
stronger model when the diff touches `riskPaths`; in light mode that diff
raises the run to medium, so the review runs. Acceptance criteria are read
from `spec.md` when it exists, otherwise from `plan.md`.

With a `tracker` (details in `jira.md`), the orchestrator runs these steps at
the stage boundaries. Each posts a `Pipeline:` comment; a failed call is a
warning and never stops the run.

| Event | Where | Comment | Transition |
| --- | --- | --- | --- |
| intake | kickoff, before the worktree | none | none; `ticket.md` is generated, the issue is assigned |
| `started` | end of kickoff | yes | to In Progress |
| `spec-done` | spec exit (heavy) | yes | none |
| `plan-approved` | after H2 | yes | none |
| `dev-done` | dev exit | yes | none |
| `review-done` | review exit (not in light unless raised) | yes | none |
| `pr-opened` | PR opened or reused | yes, with the PR link | to In Review |
| `pr-feedback-addressed` | end of a round (§5a) | yes | none |
| `merged` | merge cleanup | yes, once | to Done |
| `aborted` | abort | yes | none |

### 5a. PR follow-up

In stage `done` the session starts `scripts/watch_pr.py` in the background.
It polls the PR with `gh` once a minute and exits on new human feedback (not
from a bot, not one of the pipeline's own replies, which carry
`<!-- gated-dev -->`, newer than `lastAddressedCommentAt`), a merge, a close,
or 5 failed polls in a row. Feedback starts a round (`--address-review` does
the same by hand): the orchestrator classifies every item as change, question
or decline in `pr-feedback-<n>.md` (asking the developer for declines,
ambiguous items and anything the escalation list of §4 covers), the dev agent
fixes the change items, the reviewer checks the new commits, then the branch is
pushed (never forced) and every item gets a marked reply. Threads are not
resolved and reviews not re-requested. A merge notifies the developer and
removes the worktree when it is clean and at the merged commit; the branch is
kept. Closing the session stops the watch; `--resume` restarts it. With a
`tracker` the issue stays In Review during feedback rounds; each round only
posts its comment.

### 5b. Dev tiers

Three dev agents share one contract and differ in weight: `ticket-dev-godzilla`
(opus, heavy), `ticket-dev-workhorse` (sonnet, normal), `ticket-dev-pawn`
(haiku, mechanical steps spelled out in the plan). The planner advises in a
`## Dev tier` section of `plan.md`. The orchestrator decides at H2, shows the
choice in the H2 summary and records it in `state.json` (`devTier`,
`devTierReason`). Rules, in order:

1. config `devTier` other than `auto` wins;
2. a tier the developer names in the H2 free text wins;
3. never `pawn` when the plan has gated operations, the diff will touch
   `riskPaths`, or a step is marked as a risk;
4. otherwise the planner's tier; without one, `workhorse`.

The mode ([modes.md](modes.md)) then bounds the tier of every dev run:
heavy → at least `workhorse`, light → at most `workhorse` (a light plan that
needs `godzilla` raises the mode instead). Promotion is not bounded by the
mode.

| Dev run | Tier |
| --- | --- |
| `MODE=implement` | `devTier` |
| `MODE=fix-review`, round 1 | `devTier` |
| `MODE=fix-review`, round 2 and later | one tier up |
| `MODE=fix-pr` | per round from `pr-feedback-<n>.md`: `pawn` when every `change` item is mechanical, else `devTier`; at least `workhorse` when an item touches `riskPaths` |

Models come from `models.devGodzilla` / `devWorkhorse` / `devPawn`
(defaults `opus` / `sonnet` / `haiku`), the fixed tier from `devTier`.

A tier out of its depth is promoted automatically, all the way up (`pawn` →
`workhorse` → `godzilla`), at most once per tier, in every dev run
(`implement`, `fix-review`, `fix-pr`), before the developer is asked:

| Agent result | Action |
| --- | --- |
| `NEEDS_DECISION` with `tier too low: <reason>` | Re-run the stage one tier up; no H-point |
| `tier too low:` from `godzilla` | H3 |
| `verification failed: ...` from `pawn` or `workhorse` (also after a promotion) | Re-run one tier up, continuing from the committed trailers |
| `verification failed: ...` from `godzilla` | H6 |
| Any other `NEEDS_DECISION` | H3; the tier does not change |
| Crash, no marker | 1 retry on the same tier, then H7 |

Each promotion is appended to `state.devTierHistory` and to `state.warnings`
with `stage: "dev-tier"`; the PR lists it nowhere under "Skipped checks".

## 6. Hosts

| Host | Detected by | Worktree created with | Removed with |
| --- | --- | --- | --- |
| Orca | `TERM_PROGRAM=Orca`, or `ORCA_TERMINAL_HANDLE` without `TERM_PROGRAM=iTerm.app`, and the repo is registered in Orca (`orca repo show --repo path:<root>`) | `orca worktree create --repo path:<root> ... --json` | `orca worktree rm` |
| iTerm2 | `TERM_PROGRAM=iTerm.app` or `ITERM_SESSION_ID` | `git worktree add --no-track -b` | `git worktree remove` |
| other | anything else (including Orca with an unregistered repo) | `git worktree add --no-track -b` | `git worktree remove` |

A session that already runs in a linked worktree (opened by a launcher or by
Orca) adopts it instead of creating one, when its branch is the ticket's or is
clean, unused and behind the base. A run started from any other checkout
adopts an existing worktree whose branch is the ticket's (`<KEY>/*`) as well,
so a key never gets a second worktree. Sessions started by hand get a `/rename`
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
  "stage": "spec | plan | awaiting_plan_approval | dev | review | complete | done | addressing_review | merged | aborted",
  "mode": "heavy | medium | light",
  "modeReason": "light: one area (apps/web copy), clear result, one file",
  "modeHistory": [{ "from": "light", "to": "medium", "by": "planner | developer | riskPaths", "stage": "awaiting_plan_approval", "reason": "...", "at": "ISO-8601" }],
  "abortedFrom": "dev",
  "reviewRound": 0,
  "devTier": "godzilla | workhorse | pawn",
  "devTierReason": "planner: 6 steps, one schema change already decided",
  "devTierHistory": [{ "from": "pawn", "to": "workhorse", "reason": "tier too low: step 3 needs a choice", "stage": "dev", "at": "ISO-8601" }],
  "decisions": [{ "stage": "plan", "question": "...", "answer": "...", "at": "ISO-8601" }],
  "warnings": [{ "stage": "dev | dev-tier", "command": "...", "reason": "...", "at": "ISO-8601" }],
  "prUrl": null,
  "lastAddressedCommentAt": "ISO-8601 (newest PR feedback handled)",
  "watch": { "pid": 123, "startedAt": "ISO-8601", "heartbeatAt": "ISO-8601" },
  "tracker": { "type": "jira", "site": "...", "url": "...", "status": "In Review", "statusAt": "ISO-8601", "pending": [] },
  "updatedAt": "ISO-8601"
}
```

`tracker` exists only when a tracker is configured; every writer of
`state.json` keeps it, as it keeps `watch`. `mode`, `modeReason` and
`modeHistory` are described in [modes.md §9](modes.md#9-records); a state
without `mode` counts as `heavy`.

`--resume` re-enters the recorded stage from its start, with the recorded
mode (a `--mode` that differs is refused). Stages are safe to run
again: they overwrite their own file, and dev skips steps whose `Plan-Step: N`
commit already exists. In stage `done` it restarts the PR watch, in
`addressing_review` the feedback round, in `merged` the cleanup. Only the
watcher writes `watch`. Abort keeps the worktree and branch.

## 8. Not in this version

- Running without a developer present, or in CI.
- Picking the next ticket from a tracker (parent-based picker).
- Trackers other than Jira.
