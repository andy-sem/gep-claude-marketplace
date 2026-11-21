# Task 16: `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`

Package **J3** · prev [Task 15](J3-15-workflow-plan.md) · [index](README.md)

> Two files in one task: the version and description must match in both, and `claude plugin validate .` checks them together.

## Goal

Release the feature: `gated-dev-simple-workflow` 0.9.1 → **0.10.0** (new feature), catalog `metadata.version` 0.20.3 → **0.21.0**. Re-read both values before editing, since other work may have bumped them.

## Changes

1. `plugins/gated-dev-simple-workflow/.claude-plugin/plugin.json`:
   - `version`: `0.10.0`.
   - `description`: "File-based ticket-to-PR pipeline" becomes "Ticket-to-PR pipeline for ticket files or Jira issues". Add "With a Jira tracker it moves the issue To Do → In Progress → In Review → Done and posts progress comments, using the session's Jira tools." Keep the rest, including "Projects can add their own steps at fixed events".
   - `keywords`: add `jira`.
2. `.claude-plugin/marketplace.json`: the same `version` and `description` in the plugin's entry; `metadata.version` `0.21.0`.

## Steps

- [ ] **1.** Edit both files.
- [ ] **2.** Release checks:

  ```bash
  claude plugin validate .
  jq . .claude-plugin/marketplace.json
  uv run pytest
  uv run ruff check .
  ```

- [ ] **3. Commit J3** (stage by name: `skills/launch/SKILL.md`, the plugin `README.md`, `tests/test_no_named_mcp.py`, `CLAUDE.md`, `docs/plans/gated-dev-simple-workflow.md`, `plugin.json`, `marketplace.json`): `Jira tracker J3: docs, guard test, release 0.10.0`. Push only when the user asks.
- [ ] **4.** Run the manual acceptance of the [index](README.md#acceptance-after-j3-by-hand) and record the outcome in `docs/plans/gated-dev-simple-workflow.md` §7 (Task 15, step 4).

## Done when

- Validation and tests are green, J3 is one commit, and the acceptance run is recorded.
