# Task 15: `docs/plans/gated-dev-simple-workflow.md`

Package **J3** · prev [Task 14](J3-14-claude-md.md) · next [Task 16](J3-16-release.md) · [index](README.md)

## Goal

The workflow plugin's binding plan records that the "file-based, no Jira" decision was reversed, so §7 (the entry point for a new session) does not send anyone the wrong way.

## Changes

1. **§3 Plugin B, item 1 "File-based, no tracker."** Keep the history: add "Superseded 2026-11-21: optional Jira tracker, see `docs/plans/jira-tracker/`."
2. **§5 Decisions table, row "Ticket source for the workflow":** add a new row below it: "Ticket source (revised) | Files, or Jira through the session's own Jira tools when `tracker` is configured; stage agents stay tracker-free; In Review added on PR open (user, 2026-11-21)". Mark the old row "superseded".
3. **§7 "Decisions made with the user (binding)":** the bullet "**The workflow is file-based; no Jira support.**" becomes "file-based between stages; Jira optional at the edges (2026-11-21, `docs/plans/jira-tracker/`)". The "MCP stays generic" bullet stays as it is.
4. **§7 Status table:** add a row "Jira tracker J1–J3 | <status> | <commit>" and fill it in when J3 lands.
5. **§7 Known gaps / later:** add "Parent-based picker (needs the driver loop)".

## Steps

- [ ] **1.** Edit. Do not mention the source project's name or keys (memory note; `CLAUDE.md` hygiene).

## Done when

- A new session that reads §7 learns that Jira is supported and where the plan is.
