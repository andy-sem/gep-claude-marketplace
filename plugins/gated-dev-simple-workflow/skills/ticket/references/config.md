# Configuration: `.claude/gated-dev.json`

Optional, per project, in the checkout the session starts in. Every key is
optional; a missing file means all defaults. Invalid JSON or an unknown key
stops the run with a message (nothing is guessed).

```json
{
  "ticketsDir": "docs/tickets",
  "keyPattern": "^[A-Z]+-\\d+$",
  "baseBranch": "develop",
  "setupCommand": "npm ci",
  "formatCommand": "prettier --write",
  "riskPaths": ["**/migrations/**", "src/auth/**", "infra/**"],
  "escalationExtra": [
    "any change to the public API of packages/sdk",
    "a migration that is not additive"
  ],
  "models": { "plan": "opus", "reviewRisk": "opus" },
  "orchestratorRules": ".claude/gated-dev-rules.md",
  "dryRunGate": false,
  "tracker": {
    "type": "jira",
    "site": "acme.example.net",
    "statuses": { "inProgress": "In Progress", "inReview": "In Review", "done": "Done" }
  }
}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `ticketsDir` | `docs/tickets` | Repo-relative directory of the ticket directories. A ticket's files live in `<ticketsDir>/<KEY>/`. |
| `keyPattern` | `^[A-Za-z][A-Za-z0-9._-]*$`; with a `tracker`, `^[A-Z][A-Z0-9]*-\d+$` | Regex a ticket key must match. Keys never contain `/` or `..`. |
| `baseBranch` | remote default branch, else `main` | Branch new ticket branches start from and PRs target. A ticket's front matter `base:` overrides it. |
| `setupCommand` | none | Run once in a new worktree (for example a dependency install). Failure: H6. |
| `formatCommand` | none | Formatter; the files to format are appended. Passed to the dev agent as `FORMAT_CMD=`. |
| `riskPaths` | see SKILL.md section 8 | Globs; when the diff touches one, the reviewer runs on `models.reviewRisk`. Replaces the default list. |
| `escalationExtra` | `[]` | Project-specific cases every agent must escalate; passed as `PROJECT_RULES:`. |
| `models` | `spec: sonnet`, `plan: opus`, `dev: sonnet`, `review: sonnet`, `reviewRisk: opus` | Model per stage; keys given here override the defaults one by one. |
| `orchestratorRules` | none | Repo-relative path to a Markdown file of extra orchestrator steps, one `## <event>` section per event (SKILL.md section 0a). A missing file or an unknown event heading stops the run. A ticket without `ticket.md` may then be started: the `intake` section writes it. |
| `tracker` | none (the ticket is a file) | Takes the ticket from an issue tracker instead of a hand-written `ticket.md`. Only Jira is supported; see [Tracker: Jira](#tracker-jira). |
| `dryRunGate` | `false` | `true`: the planner dry-runs the calls it lists through `destructive-guard:check` and fills the `Gate` column of `## Gated operations` (`ask (risk 0.86)`); otherwise the column says `unknown`. Each checked call is one request to the gate's risk classifier and sends the redacted command, so it is off by default. Must be a boolean. `/ticket-flow` runs `/ticket` sessions and inherits the setting; nothing in the flow code calls the gate. |
| `flow` | none | Settings of `/ticket-flow`, which runs the subtasks of a Jira parent. Needs a `tracker`; see [Flow](#flow). |

## Tracker: Jira

Opt-in. Without a `tracker` key the pipeline is file-based and makes no Jira
call. With it, the orchestrator uses the Jira tools of the session (no API
tokens, no client of its own); behaviour is described in
[jira.md](jira.md).

```json
"tracker": {
  "type": "jira",
  "site": "acme.example.net",
  "statuses": { "inProgress": "In Progress", "inReview": "In Review", "done": "Done" },
  "startFrom": ["To Do", "Backlog", "Selected for Development"],
  "assign": true,
  "comments": true,
  "baseFromParent": "feature/{parent}/*"
}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `type` | required | Only `jira`. Any other value stops the run. |
| `site` | the only site the tools can reach; otherwise kickoff asks once and suggests setting the key | Jira site host name. |
| `statuses.inProgress` / `.inReview` / `.done` | `In Progress` / `In Review` / `Done` | Target status names, matched without regard to case. `inReview: null` skips that step (for workflows without In Review). |
| `startFrom` | any status in Jira's To Do category | Statuses kickoff may move to In Progress. |
| `assign` | `true` | Assign the issue to the current user at kickoff. |
| `comments` | `true` | Post the `Pipeline:` comments. Status changes happen either way. |
| `baseFromParent` | unset | Branch glob containing `{parent}`. Exactly one matching branch on `origin` becomes the base; none means the normal base rules apply; more than one asks. |

- An unknown sub-key or a wrong type (for example a string for `assign`)
  stops the run with a message.
- `keyPattern` defaults to `^[A-Z][A-Z0-9]*-\d+$` (Jira keys such as `PROJ-1`).
- `orchestratorRules` may not have a `## intake` section when a `tracker` is
  set, because the tracker does the intake. That is a config error.

## Flow

Optional, for `/ticket-flow` (pick rules and state: [flow.md](flow.md)). Setting
`flow` without a `tracker` is a config error.

```json
"flow": {
  "max": 1,
  "jql": "parent = {parent} ORDER BY Rank ASC",
  "pickRules": [
    "prefer the earliest phase or workstream; summaries look like 'P1 WS2: ...'"
  ],
  "pollSeconds": 60,
  "staleHours": 3,
  "lostWatchMinutes": 10,
  "remoteControl": false
}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `max` | `1` | Runs holding a slot at once. 1 to 10. |
| `jql` | `parent = {parent} ORDER BY Rank ASC` | Candidate query; must contain `{parent}`. The order is the base priority. |
| `pickRules` | `[]` | Extra plain-language rules for the judgement step of the pick. |
| `pollSeconds` | `60` | Poll interval of `flow.py wait`. 15 to 3600. |
| `staleHours` | `3` | A slot-holding run whose `state.json` has not changed for this long is reported once. |
| `lostWatchMinutes` | `10` | A `done` run with an open PR and a watch heartbeat older than this has lost its watch; the driver reopens its session. |
| `remoteControl` | `false` | Launch sessions with `--remote-control`. |

An unknown sub-key or a wrong type stops the run with a message. The flags
`--max N` and `--once` of `/ticket-flow` override per run; `--max` is stored in
the flow state, so a continued flow keeps it.

## The ticket file

`<ticketsDir>/<KEY>/ticket.md`, written by the developer (or by `/ticket`
from a pasted description), or, with a `tracker`, generated from Jira. The first `# ` heading is the title; it names
the branch (`<KEY>/<slug>`) and the PR. Optional front matter:

```markdown
---
base: release/2.x
---

# Export reports as CSV

Users want to export a report ... (free text: goal, context, links, notes)
```

With a `tracker`, kickoff generates the file from the Jira issue. Its front
matter has `tracker: jira`, `url`, `type`, `status`, `parent` and `fetchedAt`,
plus `base` when `baseFromParent` found a branch. The orchestrator uses only
`base:` and `tracker:`; the rest is for readers. A hand-written file with no
`tracker:` key is kept only if the developer chooses that at kickoff.

The spec agent reads only this file and the repository. Commit it on the
base branch, or leave it untracked in the main checkout: kickoff copies it
into the ticket worktree, and it is committed there with the spec and plan.

## Files per ticket

| File | Written by | Committed |
| --- | --- | --- |
| `ticket.md` | developer / kickoff, or generated from Jira | at plan approval |
| `spec.md` | spec agent | at plan approval |
| `plan.md` | planner | at plan approval |
| `decisions.md` | orchestrator | at plan approval, then on every append |
| `dev-report.md` | dev agent | by the dev agent |
| `review.md` | reviewer | after each review round |
| `state.json` | orchestrator | never (ignored through `.git/info/exclude`) |
