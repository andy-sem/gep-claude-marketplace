# Jira tickets for `gated-dev-simple-workflow`: implementation plan

> **One task = one file in this folder, and each task changes one file of the repo.** There are two exceptions: Task 05 makes the same one-line change in the four agent files, and Task 16 bumps the version in `plugin.json` and the catalog together, because `claude plugin validate .` needs both. Tasks are grouped into work packages J1–J3. The last task of each package makes the package's single commit (repo rule: one commit per work package). Every task leaves `uv run pytest` and `uv run ruff check .` green.

**Goal:** `/ticket PROJ-1` can take its ticket from Jira instead of from `ticket.md`.

**File handling stays the default.** Jira is an opt-in per project: it is on only when `.claude/gated-dev.json` contains `"tracker": {"type": "jira", ...}`. With no `tracker` key (or no config file at all) the pipeline behaves exactly as today: `ticket.md` is the ticket, no Jira tools are needed, and no Jira call is ever made. Every Jira step in the skill is guarded by "when `tracker` is configured", and the J2 tests pin both modes (`test_read_config_without_tracker_is_unchanged`).

With Jira enabled, the orchestrator:

- fetches the issue at kickoff (summary, description, type, status, parent, links, recent human comments) and writes it to `ticket.md`, so the stage agents stay file-based and unchanged;
- assigns the issue to the current user and moves it **To Do → In Progress** at kickoff;
- moves it **In Progress → In Review** when the PR is opened (or reused);
- moves it **→ Done** after the PR is merged;
- posts a short `Pipeline:` comment (Done / Next / Blockers) at each stage transition;
- treats a failed Jira call as a warning that never stops the run (except at kickoff, where the issue must be readable).

Without `tracker` nothing changes: the pipeline stays file-based.

**Source:** the private source project's `/ticket` skill (its §3 step 1 and step 8, §9a step 5, §9d step 2, §10, §11). This plan keeps its behaviour and adds the **In Review** step, which the source never had (it moved only To Do → In Progress and → Done). Do not copy any name, key or id from the source (see `CLAUDE.md`, public repo hygiene).

## Decisions (user, 2026-11-21)

| Topic | Decision |
| --- | --- |
| Ticket source | **Files by default**; Jira only when the project enables it with the `tracker` config key. This reverses the binding "file-based, no Jira" decision of 2026-11-19 (Task 15 records it). |
| How Jira is reached | **The session's own Jira tools** (whatever Jira MCP server or connector the user has), described by capability (read an issue, list and apply transitions, comment, assign, current user). No Python Jira client, no API tokens. Shipped files never name an MCP server or its tool names (repo hygiene; Task 13 adds a guard test). |
| Parent-based picker | **Not in this plan** (see [Not in this plan](#not-in-this-plan)). |

## Design

### Where the Jira logic lives

- **New reference `skills/ticket/references/jira.md`** (Task 01) is the single description of Jira behaviour: config, intake, the status lifecycle, comments, failure handling and `state.tracker`. `SKILL.md` calls it at fixed points instead of repeating it.
- **`SKILL.md`** (Task 04) adds **Tracker `<event>`** steps at the existing events of section 0a (`started`, `resumed`, `spec-done`, `plan-approved`, `dev-done`, `review-done`, `pr-body`, `pr-opened`, `pr-feedback-addressed`, `merged`, `aborted`) plus intake. At each event the tracker step runs first, then the `orchestratorRules` section, if any. With a tracker the rules may not have a `## intake` section (config error), because the tracker does the intake.
- **Stage agents stay tracker-free.** The spec agent still reads only `ticket.md`. The agents get one generic rule: never change anything outside the worktree through any tool (Task 05). They inherit the session's MCP tools, so without that rule a subagent could comment on or move the issue.
- **Launcher** (`scripts/gated_dev/launch/`, Tasks 06–10) accepts and checks the `tracker` key. With a tracker it opens a session for a key that has no `ticket.md` yet, as it already does for `orchestratorRules`.
- **No change** to the PR watcher, `notify.py`, the hooks or `destructive-guard`. The gate's `mcp-destructive-tool` words (`delete`, `remove`, ...) do not match reading, commenting, assigning or transitioning, so the Jira calls cause no gate prompts.

### Config

```json
{
  "tracker": {
    "type": "jira",
    "site": "acme.example.net",
    "statuses": { "inProgress": "In Progress", "inReview": "In Review", "done": "Done" },
    "startFrom": ["To Do", "Backlog", "Selected for Development"],
    "assign": true,
    "comments": true,
    "baseFromParent": "feature/{parent}/*"
  }
}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `type` | required | Only `jira` for now. |
| `site` | the only site the tools can reach; otherwise kickoff asks once and suggests setting the key | Jira site host name. |
| `statuses.inProgress` / `.inReview` / `.done` | `In Progress` / `In Review` / `Done` | Target status names, matched without regard to case. `inReview: null` skips that step (for workflows without In Review). |
| `startFrom` | any status in Jira's *To Do* category | Statuses kickoff may move to In Progress. |
| `assign` | `true` | Assign the issue to the current user at kickoff. |
| `comments` | `true` | Post the `Pipeline:` comments. Status changes happen either way. |
| `baseFromParent` | unset | Branch glob with `{parent}`. Exactly one matching branch on `origin` becomes the base; zero means the normal base rules apply; more than one asks (H3). |

With a tracker, the default `keyPattern` becomes `^[A-Z][A-Z0-9]*-\d+$`.

### Status lifecycle (forward only)

| When | Moves | Only if the current status is |
| --- | --- | --- |
| Kickoff (`started`) | → `inProgress` | in `startFrom` (or the To Do category) |
| PR opened or reused (`pr-opened`) | → `inReview` | `inProgress` or a `startFrom` status |
| PR merged (`merged`) | → `done` | not already `done` |
| Abort, restart, PR feedback rounds, resume | none | — |

A transition is found by listing the issue's transitions and taking the one whose **target status** has the configured name, else the one whose own name matches. None found: a `tracker` warning (`no transition to <X> from <Y>`), and the run goes on. The pipeline never moves an issue backwards and makes no other status change. `/ticket <KEY>` with a tracker configured authorises these reads, the assignment, the three transitions and the comments. They need no extra question (pipeline-spec §3).

### Intake (`ticket.md` from Jira)

Kickoff step 1 with a tracker always fetches the issue. If the issue is missing or cannot be read, kickoff stops and nothing is created. It writes `<session-root>/<ticketsDir>/<KEY>/ticket.md`:

```markdown
---
tracker: jira
url: https://acme.example.net/browse/PROJ-1
type: Story
status: To Do
parent: PROJ-0
base: feature/PROJ-0/reports   # only when baseFromParent finds exactly one branch
fetchedAt: 2026-11-21T10:00:00Z
---

# <summary>

<description, converted to Markdown>

## Parent

PROJ-0: <summary> (<status>)

## Linked issues

- is blocked by PROJ-2: <summary> (Done)

## Recent comments

- <author>, <date>: <body>   (the last 5 human comments; `Pipeline:` comments are left out)
```

- A file with `tracker: jira` in its front matter was generated: it is rewritten from Jira.
- A hand-written file (no `tracker:` key): ask **Use Jira (recommended)** · **Keep the file**.
- A description pasted with the command is appended under `## Notes from the developer`.
- On `--resume`, refetch the issue. If the summary or description changed: before H2, rewrite `ticket.md` and say so; from stage `dev` on, ask **Keep the current spec (recommended)** · **Re-run from spec** (which sets the stage to `spec` and rewrites `ticket.md`).

### State

`state.json` gets `tracker`: `{type, site, url, status, statusAt, pending: [<comment bodies not yet posted>]}`. Re-read it and keep it on every write, like `rules`. A failed call adds `{stage: "tracker", command, reason, at}` to `state.warnings`. Failed comments queue in `pending` and are posted, oldest first, before the next comment. `--status` shows the last known Jira status and may do one read-only fetch. The PR's "Skipped checks" leaves out `tracker` warnings.

### Comments

```text
Pipeline: <event> finished
Done: <what actually happened, with file paths or commit hashes>
Next: <the next stage, or "waiting for plan approval">
Blockers: <none, or the open question or warning>
```

Posted at `started`, `spec-done`, `plan-approved`, `dev-done`, `review-done`, `pr-opened` (with the PR link; also a remote link when the tools support one), `pr-feedback-addressed`, `merged` and `aborted`, plus one for every H-answer that changes scope. `merged` is skipped when the issue already has a `Pipeline: PR merged` comment, so re-running section 9d is safe.

## Tasks

| # | Package | File | What |
| --- | --- | --- | --- |
| [01](J1-01-jira-reference.md) | J1 | `skills/ticket/references/jira.md` (new) | The Jira contract |
| [02](J1-02-config-reference.md) | J1 | `skills/ticket/references/config.md` | `tracker` key, generated `ticket.md` |
| [03](J1-03-pipeline-spec.md) | J1 | `skills/ticket/references/pipeline-spec.md` | Principles, authorisation, lifecycle, state |
| [04](J1-04-ticket-skill.md) | J1 | `skills/ticket/SKILL.md` | Tracker steps in the orchestrator |
| [05](J1-05-agents.md) | J1 | `agents/ticket-{spec,planner,dev,reviewer}.md` | "Nothing outside the worktree" rule; **commit J1** |
| [06](J2-06-test-launch-units.md) | J2 | `tests/test_launch_units.py` | Failing tests for config and launch (TDD) |
| [07](J2-07-ticket-project.md) | J2 | `scripts/gated_dev/launch/ticket_project.py` | Accept and check `tracker` |
| [08](J2-08-test-launch-cli.md) | J2 | `tests/test_launch_cli.py` | CLI dry run of a Jira key without `ticket.md` |
| [09](J2-09-launcher.md) | J2 | `scripts/gated_dev/launch/launcher.py` | Open a session without `ticket.md` |
| [10](J2-10-launch-cli.md) | J2 | `scripts/gated_dev/launch/cli.py` | Help text; **commit J2** |
| [11](J3-11-launch-skill.md) | J3 | `skills/launch/SKILL.md` | Jira keys in the launcher skill |
| [12](J3-12-plugin-readme.md) | J3 | `plugins/gated-dev-simple-workflow/README.md` | User docs |
| [13](J3-13-test-no-named-mcp.md) | J3 | `tests/test_no_named_mcp.py` (new) | Hygiene guard |
| [14](J3-14-claude-md.md) | J3 | `CLAUDE.md` | Repo guidance |
| [15](J3-15-workflow-plan.md) | J3 | `docs/plans/gated-dev-simple-workflow.md` | Record the reversed decision |
| [16](J3-16-release.md) | J3 | `plugin.json` + `.claude-plugin/marketplace.json` | 0.10.0 / catalog 0.21.0; **commit J3** |

Paths without a leading directory are under `plugins/gated-dev-simple-workflow/`.

## Acceptance (after J3, by hand)

There are no tests for skills or agents, so check the Markdown side end to end in a demo repo with a sandbox Jira project (never a real team project):

1. `.claude/gated-dev.json` with `tracker`. Run `/ticket PROJ-1` on a To Do issue. Check that `ticket.md` is generated, the issue is assigned and In Progress, and a `Pipeline: started` comment exists.
2. Approve the plan and let it run to the PR. Check that the issue is In Review and has a comment with the PR link.
3. Comment on the PR and let the watch address it: the status stays In Review and a `PR feedback round 1 addressed` comment appears.
4. Merge: the issue is Done, there is one `Pipeline: PR merged` comment, and the worktree is removed. Run `/ticket PROJ-1 --resume`: no second merged comment.
5. Failure path: set `statuses.inReview` to a name the workflow lacks. The run finishes with a `tracker` warning shown by `--status` and not listed in the PR.
6. A session without Jira tools: kickoff stops before creating a worktree, with the message from Task 04.

## Not in this plan

- **Parent-based picker** (the source's `ticket:flow start <PARENT>` loop). It is a long-running driver, not a one-shot launcher. Each pass it syncs every tracked ticket's `state.json` and PR, opens review and cleanup tabs, and then, for each free slot (`running` < `--max`), runs one `claude -p` call with only Jira *read* tools allowed and a JSON schema. That call returns the top-ranked To Do subtask of the parent whose blockers are Done, and the driver opens a tab with `/ticket <KEY>`. Porting it means porting the loop, `flow.json` and the sync logic too, and its `--allowedTools` list would need configurable tool names (hygiene). It needs its own plan.
- Other trackers (GitHub Issues, Linear). `tracker.type` leaves room for them.
- Moving the issue back to In Progress during PR feedback rounds.
