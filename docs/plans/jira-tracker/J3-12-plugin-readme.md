# Task 12: `plugins/gated-dev-simple-workflow/README.md`

Package **J3** · prev [Task 11](J3-11-launch-skill.md) · next [Task 13](J3-13-test-no-named-mcp.md) · [index](README.md)

## Goal

The user-facing README explains Jira tickets.

## Changes

1. **Intro (lines 1–8):** "By default the ticket is a Markdown file ...; a project can **switch to Jira issues** instead (see [Jira](#jira))". Drop "The pipeline uses no issue tracker itself". The Jira section opens with: "Off by default. Without `tracker` nothing in this section applies."
2. **New section `## Jira`** after the configuration section:
   - Requirement: a Jira MCP server or connector in the Claude Code session, with read, transition, comment and assign rights. Describe it generically; name no server.
   - Minimal config: `{"tracker": {"type": "jira", "site": "acme.example.net"}}`.
   - The lifecycle table (To Do → In Progress → In Review → Done, and when each move happens) and "never backwards, nothing else".
   - What lands in Jira: assignment and `Pipeline:` comments; `comments: false` turns comments off.
   - How to customise status names (`statuses`, `inReview: null`) and `baseFromParent`.
   - Failures are warnings shown by `/ticket KEY --status`; kickoff stops only when the issue cannot be read or the session has no Jira tools.
   - The stage agents never touch Jira; `ticket.md` is generated and committed with the spec and plan.
3. **`### Project rules`:** the example in it currently mimics Jira (intake, In Progress, Done). Replace it with a non-Jira example (for example a chat notification at `pr-opened` and `merged` with a made-up tool, or a changelog line at `plan-approved`). Add one sentence: with a tracker, rules run after the tracker step and may not define `intake`.
4. **Launching section:** a Jira key without `ticket.md` opens in the main checkout titled with the plain key.

## Steps

- [ ] **1.** Edit.
- [ ] **2.** `grep -nE 'mcp__|atlassian' plugins/gated-dev-simple-workflow/README.md`: only made-up `mcp__tracker__`-style names, if any.

## Done when

- The README is in sync with `config.md` and `jira.md` (CLAUDE.md: "keep it in sync with behaviour").
