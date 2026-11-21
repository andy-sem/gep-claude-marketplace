# Task 14: `CLAUDE.md`

Package **J3** · prev [Task 13](J3-13-test-no-named-mcp.md) · next [Task 15](J3-15-workflow-plan.md) · [index](README.md)

## Goal

The repo guidance matches the new behaviour, so future sessions do not "fix" the Jira support away.

## Changes

1. **Concept table, `gated-dev-simple-workflow` row:** "File-based ticket → ... pipeline" becomes "Ticket (file or Jira issue) → spec → plan → dev → review → PR pipeline".
2. **§ `gated-dev-simple-workflow`, the "File-based" bullet:** replace "**No issue tracker (no Jira)**: agents have no tracker tools or wording." with: "Optional Jira tracker (`tracker` in `.claude/gated-dev.json`, behaviour in `skills/ticket/references/jira.md`): the orchestrator fetches the issue into `ticket.md` and moves it To Do → In Progress → In Review → Done using the session's own Jira tools. The stage agents stay tracker-free. Never name an MCP server or its tools in shipped files (`tests/test_no_named_mcp.py`)."
3. **Public repo hygiene:** add to the MCP bullet "the workflow's Jira support included".
4. **Work in progress:** add a pointer: "Jira tracker plan: `docs/plans/jira-tracker/README.md`."

## Steps

- [ ] **1.** Edit. The file is checked in; neutral placeholders only.

## Done when

- `CLAUDE.md` no longer says "no Jira", and it names the reference, the config key and the guard test.
