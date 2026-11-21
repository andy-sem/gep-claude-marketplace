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
  "orchestratorRules": ".claude/gated-dev-rules.md"
}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `ticketsDir` | `docs/tickets` | Repo-relative directory of the ticket directories. A ticket's files live in `<ticketsDir>/<KEY>/`. |
| `keyPattern` | `^[A-Za-z][A-Za-z0-9._-]*$` | Regex a ticket key must match. Keys never contain `/` or `..`. |
| `baseBranch` | remote default branch, else `main` | Branch new ticket branches start from and PRs target. A ticket's front matter `base:` overrides it. |
| `setupCommand` | none | Run once in a new worktree (for example a dependency install). Failure: H6. |
| `formatCommand` | none | Formatter; the files to format are appended. Passed to the dev agent as `FORMAT_CMD=`. |
| `riskPaths` | see SKILL.md section 8 | Globs; when the diff touches one, the reviewer runs on `models.reviewRisk`. Replaces the default list. |
| `escalationExtra` | `[]` | Project-specific cases every agent must escalate; passed as `PROJECT_RULES:`. |
| `models` | `spec: sonnet`, `plan: opus`, `dev: sonnet`, `review: sonnet`, `reviewRisk: opus` | Model per stage; keys given here override the defaults one by one. |
| `orchestratorRules` | none | Repo-relative path to a Markdown file of extra orchestrator steps, one `## <event>` section per event (SKILL.md section 0a). A missing file or an unknown event heading stops the run. A ticket without `ticket.md` may then be started: the `intake` section writes it. |

## The ticket file

`<ticketsDir>/<KEY>/ticket.md`, written by the developer (or by `/ticket`
from a pasted description). The first `# ` heading is the title; it names
the branch (`<KEY>/<slug>`) and the PR. Optional front matter:

```markdown
---
base: release/2.x
---

# Export reports as CSV

Users want to export a report ... (free text: goal, context, links, notes)
```

The spec agent reads only this file and the repository. Commit it on the
base branch, or leave it untracked in the main checkout: kickoff copies it
into the ticket worktree, and it is committed there with the spec and plan.

## Files per ticket

| File | Written by | Committed |
| --- | --- | --- |
| `ticket.md` | developer / kickoff | at plan approval |
| `spec.md` | spec agent | at plan approval |
| `plan.md` | planner | at plan approval |
| `decisions.md` | orchestrator | at plan approval, then on every append |
| `dev-report.md` | dev agent | by the dev agent |
| `review.md` | reviewer | after each review round |
| `state.json` | orchestrator | never (ignored through `.git/info/exclude`) |
