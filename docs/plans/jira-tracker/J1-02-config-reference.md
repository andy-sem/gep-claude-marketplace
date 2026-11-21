# Task 02: `skills/ticket/references/config.md`

Package **J1** · prev [Task 01](J1-01-jira-reference.md) · next [Task 03](J1-03-pipeline-spec.md) · [index](README.md)

## Goal

The config reference documents the `tracker` key and the generated `ticket.md`.

## Changes

1. **Example JSON** (top of the file): add a `tracker` object with `type`, `site` and `statuses` only. The full key list goes in the table.
2. **Key table:** add a `tracker` row (default: none, meaning a file-based ticket) that points to a new subsection.
3. **New subsection `## Tracker: Jira`:** the sub-key table from the README (`type`, `site`, `statuses.*`, `startFrom`, `assign`, `comments`, `baseFromParent`), the default `keyPattern` with a tracker, the rule that an unknown sub-key or a wrong type stops the run, and the rule that `orchestratorRules` may not have a `## intake` section when a tracker is set. Link to `jira.md` for behaviour.
4. **`keyPattern` row:** note the tracker default `^[A-Z][A-Z0-9]*-\d+$`.
5. **`## The ticket file`:** add a paragraph saying that with a tracker the file is generated from Jira at kickoff (front matter `tracker: jira`, `url`, `type`, `status`, `parent`, `fetchedAt`, optional `base`), and that the orchestrator uses only `base:` and `tracker:`. A hand-written file with no `tracker:` key is kept only if the developer chooses that.
6. **Files per ticket table:** `ticket.md`, "Written by": add "or generated from Jira".

## Steps

- [ ] **1.** Make the edits above. Keep the table format of the file.
- [ ] **2.** Check that every sub-key named here exists in Task 07's validation list (the same names, the same types).

## Done when

- A reader can configure Jira from this file alone without opening `jira.md`; `jira.md` explains what each key does at run time.
