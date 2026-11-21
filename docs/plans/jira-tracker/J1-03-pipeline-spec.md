# Task 03: `skills/ticket/references/pipeline-spec.md`

Package **J1** · prev [Task 02](J1-02-config-reference.md) · next [Task 04](J1-04-ticket-skill.md) · [index](README.md)

## Goal

The design document allows a tracker at the edges of the pipeline and says what a tracker run authorises.

## Changes

1. **§2 Principles:**
   - Rename "Files, not trackers" to **"Files between stages"**: stages still pass context only through files in the ticket directory. Add: "An issue tracker (Jira, `tracker` config) is read once at kickoff into `ticket.md` and updated by the orchestrator at fixed events; stage agents never use it."
   - "Project steps are additions": add that tracker steps run before the project's rules at the same event.
2. **§3, after the H-point table** (the paragraph "Approving the plan also authorises ..."): add that with a tracker, `/ticket <KEY>` itself authorises reading the issue, assigning it, the three forward transitions of `jira.md` §4 and the `Pipeline:` comments. The first two happen before H2. Nothing else in the tracker is ever changed.
3. **§5 Stages:** one line per stage boundary saying which tracker step runs there, or a short table (event → comment → transition) that links to `jira.md`.
4. **§5a PR follow-up:** the issue stays In Review during feedback rounds.
5. **§7 State:** add `"tracker": { "type": "jira", "site": "...", "url": "...", "status": "In Review", "statusAt": "ISO-8601", "pending": [] }` to the JSON, and one sentence: every writer keeps it, as it keeps `watch`.
6. **§8 Not in this version:** add "Picking the next ticket from a tracker (parent-based picker)" and "Trackers other than Jira".

## Steps

- [ ] **1.** Make the edits. Keep section numbers stable: `SKILL.md` and `README.md` refer to `§3`, `§4`, `§5a`, `§7`.
- [ ] **2.** `grep -n "tracker" plugins/gated-dev-simple-workflow/skills/ticket/references/pipeline-spec.md` and read every hit in context.

## Done when

- Nothing in the spec contradicts Task 01. Principle 1 still holds for the stage agents.
