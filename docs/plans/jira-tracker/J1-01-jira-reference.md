# Task 01: `skills/ticket/references/jira.md` (new)

Package **J1** (tasks 01–05) · next [Task 02](J1-02-config-reference.md) · [index](README.md)

> Read [README.md](README.md) first. Its Design section is the source of truth; this file turns it into the reference the orchestrator reads.

## Goal

A new reference, `plugins/gated-dev-simple-workflow/skills/ticket/references/jira.md`, holds all the Jira behaviour. `SKILL.md` (Task 04) refers to its sections by number and does not repeat them.

## Sections to write

1. **Tools.** Describe what is needed by capability only: read an issue (fields, parent, links, comments), list an issue's transitions, apply a transition, add a comment, assign, read the current user, and optionally add a remote link. Use "the Jira tools of this session", never an MCP server or tool name. If any of the first six is missing at kickoff, stop with: `tracker "jira" is configured, but this session has no Jira tools (read issue, transitions, comment, assign). Connect a Jira server or remove "tracker" from .claude/gated-dev.json.`
2. **Site.** Use `tracker.site`. If it is unset and the tools reach exactly one site, use that one. If they reach several, ask once (H3) and suggest setting the key. Store it in `state.tracker.site`, together with any site id the tools need, so later calls do not look it up again.
3. **Intake.** The `ticket.md` format and the four rules from the README (generated file rewritten, hand-written file → ask, pasted text → `## Notes from the developer`, resume refetch). Also: Jira rich text is converted to Markdown, keeping headings, lists, code and links; attachments are listed by name only; and `baseFromParent` resolution with `git ls-remote --heads origin "<glob with {parent} replaced>"`.
4. **Status lifecycle.** The forward-only table, transition lookup (target status name first, then the transition name, case-insensitive), and the rule that no other status change is ever made.
5. **Comments.** The format, the event list, the `Pipeline:` prefix, the idempotency rule for `merged`, the `comments: false` switch, and "post every queued `pending` comment, oldest first, before the new one".
6. **Failures.** Every call other than the kickoff read: on failure append `{stage: "tracker", command: "<operation>", reason, at}` to `state.warnings` and continue. Retry nothing on the spot. A failed comment goes to `state.tracker.pending`. A failed transition is retried once at the next event, then left as a warning.
7. **State.** The `state.tracker` object and its fields. Every writer keeps it.
8. **Authorisation.** `/ticket <KEY>` with a tracker authorises exactly these operations. Anything else in Jira (creating issues, editing fields other than the assignee, other transitions, deleting) is never done, even when a rules file asks for it.

## Steps

- [ ] **1.** Write the file. Keep the style of `pipeline-spec.md`: short sections, tables where they help, no emoji.
- [ ] **2.** Make sure no MCP server or tool name appears in it: `grep -nE 'mcp__|atlassian' plugins/gated-dev-simple-workflow/skills/ticket/references/jira.md` prints nothing.
- [ ] **3.** Use only placeholder keys and sites (`PROJ-1`, `PROJ-0`, `acme.example.net`).

## Done when

- The file covers sections 1–8 and agrees with the README's Design section, word for word on names (`inProgress`, `inReview`, `done`, `startFrom`, `state.tracker.pending`).
- No commit yet (Task 05 commits J1).
