# Task 05: `agents/ticket-{spec,planner,dev,reviewer}.md`

Package **J1** · prev [Task 04](J1-04-ticket-skill.md) · next [Task 06](J2-06-test-launch-units.md) · [index](README.md)

> This task changes four files (the same rule in each), the only deviation from "one task, one file". Splitting it would give four one-line tasks.

## Goal

Stage subagents inherit the session's tools, including the Jira tools. They must never use them. The ticket reaches them only as `ticket.md`.

## Change

In each agent's `## Working rules` add one line, worded without naming any tracker or server:

> Never change anything outside `WORKTREE` through any tool: issue trackers, chat, cloud consoles, other repositories. The orchestrator makes every outside update.

In `ticket-dev.md`, replace "Do not push, open pull requests, reply to PR comments or edit the ticket." (around line 117) with "... or edit the ticket or its issue in a tracker." Keep the rest of the sentence.

Do **not** add `disallowedTools` entries for tracker tools. Their names differ per server and must not appear in this public repo.

## Steps

- [ ] **1.** Edit the four files.
- [ ] **2.** `grep -nE 'mcp__|atlassian|jira' plugins/gated-dev-simple-workflow/agents/*.md` prints nothing.
- [ ] **3.** Package checks:

  ```bash
  claude plugin validate .
  uv run pytest
  uv run ruff check .
  ```

- [ ] **4. Commit J1** (stage files by name: `jira.md`, `config.md`, `pipeline-spec.md`, `SKILL.md`, the four agents; plus the files of `docs/plans/jira-tracker/` if they are not committed yet): `Jira tracker J1: skill contract`. No version bump yet (Task 16).

## Done when

- J1 is one commit, and the checks are green.
