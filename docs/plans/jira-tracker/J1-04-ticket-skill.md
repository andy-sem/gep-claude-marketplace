# Task 04: `skills/ticket/SKILL.md`

Package **J1** · prev [Task 03](J1-03-pipeline-spec.md) · next [Task 05](J1-05-agents.md) · [index](README.md)

> The largest task. Section numbers below are those of the current file (265 lines). Change behaviour only where a tracker is configured: a run without `tracker` must read exactly as before.

## Goal

The orchestrator runs the Jira steps of `references/jira.md` at the right points and keeps `state.tracker`.

## Changes by section

| Section | Change |
| --- | --- |
| Frontmatter `description` | "The ticket is a Markdown file ... or a Jira issue when the project configures a tracker." Keep the trigger phrases. |
| Intro paragraph (line 17) | Replace "The pipeline itself knows no issue tracker" with: file-based between stages; with `tracker` the ticket comes from Jira and the issue is kept in step (see `references/jira.md`). |
| Rules list | Add a rule: "**Tracker `<event>`** below means: when `tracker` is configured, do what `references/jira.md` says for that event, then run the project rules' **Event `<event>`**. Without `tracker`, nothing happens." Extend the `state.json` rule to keep `tracker` as well as `watch` and `rules`. |
| §0 step 2 (config) | Add `tracker` (unset) to the defaults; with a tracker the default `keyPattern` is `^[A-Z][A-Z0-9]*-\d+$`; validate the sub-keys as in `config.md`; with both a tracker and an `orchestratorRules` `## intake` section, report a config error and stop. |
| §0 new step 5 | With a tracker, check the session has the Jira tools (`jira.md` §1) and resolve the site (§2). Missing tools: stop with the message of `jira.md` §1. This happens before section 1, so a bad setup creates nothing. |
| §0a | Add one line: tracker steps run first at every event in the table; `intake` is not available to rules when a tracker is set. |
| §2 Status | Print `state.tracker.status` and `url`; one read-only fetch of the live status is allowed. List `tracker` warnings with the others. |
| §3 step 1 | With a tracker: **Tracker intake** (`jira.md` §3) instead of the file / paste / `intake` cases. A failed read stops kickoff with the Jira error; nothing is created. |
| §3 step 2 | Front matter `base:` may come from `baseFromParent`; more than one match is H3, asked in the session and recorded once `state.json` exists (as in the source). |
| §3 step 6 | `state.json` gets `tracker` (`type`, `site`, `url`, `status`, `statusAt`, `pending: []`). |
| §3 step 9 | **Tracker `started`** before **Event `started`** (assign, To Do → In Progress, comment). |
| §4 Parse, H-answers | After recording an H1/H3 answer that changes scope, queue a tracker comment (`jira.md` §5). |
| §5–§8 | Turn every **Event `x`** into "**Tracker `x`**, then **Event `x`**": `spec-done`, `plan-approved`, `dev-done`, `review-done`. |
| §9 step 1 | **Tracker `resumed`**: refetch; on a changed summary or description, ask as `jira.md` §3 says, before the working-tree check. |
| §9a step 3 | `## Spec & plan` gets the Jira link from **Tracker `pr-body`**. "Skipped checks" leaves out warnings whose `stage` is `tracker` (and `rules`, as today). |
| §9a step 4 | **Tracker `pr-opened`**: → In Review, plus a comment with the PR link. Also when an existing PR is reused. |
| §9b step 9 | **Tracker `pr-feedback-addressed`**: comment only, no transition. |
| §9d step 2 | **Tracker `merged`**: → Done unless it is already Done, then the `Pipeline: PR merged` comment unless one exists. A failure is a warning; the worktree removal (step 4) still runs. This differs from the source, which stopped before removal; the PR is merged, so Jira lagging must not keep a worktree. Say this in the step. |
| §10 Abort | **Tracker `aborted`**: comment with the reason; no transition. |

## Steps

- [ ] **1.** Edit section by section, in file order.
- [ ] **2.** Read the whole file once with no tracker configured in mind: every new sentence must be guarded by "with a tracker" or by the **Tracker** step's definition.
- [ ] **3.** `grep -nE 'mcp__|atlassian' plugins/gated-dev-simple-workflow/skills/ticket/SKILL.md` prints nothing.
- [ ] **4.** `grep -n 'Event `' SKILL.md`: every event of the §0a table except `intake` has a **Tracker** step right before it.

## Done when

- Every row of the table above is done, and the file still reads as before for a file-based run.
