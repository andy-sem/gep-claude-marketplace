# Flow: pick rules and state

Used by `/ticket-flow` (`skills/ticket-flow/SKILL.md`), which requires a Jira `tracker`. Stage agents and `/ticket` never read this file. Settings: the `flow` key in [config.md](config.md).

## Pick

Done by the driver on Jira data; the deterministic part (state, runs, `gh`) is `scripts/flow.py`.

1. **Query.** Run `flow.jql` (default `parent = {parent} ORDER BY Rank ASC`) with `{parent}` replaced, all pages. The order is the base priority.
2. **Hard filter.** Drop a ticket, and record the reason, when:
   - its status is not in `tracker.startFrom` (default: any status in Jira's To Do category);
   - it is in the flow state, with any status (`launched`, `merged`, `aborted`, `skipped`);
   - it already has a run that this flow did not launch (started by hand): `flow.py status --candidate KEY` lists it under `foreign`; it is shown, never picked;
   - an `is blocked by` link points to an issue that is not Done. An issue whose PR this flow saw merged counts as Done even when Jira has not caught up (the `merged` status in the flow state).
3. **Judgement**, on what is left, in query order. Drop a ticket whose description names an unfinished dependency, or that needs a person (a meeting, a purchase, a contract). Apply `flow.pickRules`. Take the first ticket left.
4. **Nothing left.** Report the reason, the most useful blocker first (for example "PROJ-3 blocked by PROJ-1 (In Progress)"). The reason is shown to the developer; the flow state records the reason of a launch only.
5. **Mode.** After the pick, decide the subtask's mode from the issue just read with [modes.md section 4](modes.md#4-decision-rules-d2) (config `mode` other than `auto` is used as is; `modeRules` apply). Take the heavier mode when unsure.
6. **Launch.** `flow.py launch --parent PARENT KEY --summary "<summary>" --reason "<pick reason>; mode <mode>: <reason>" --mode <mode>`. The driver never launches without `--mode`. The pick reason is a short sentence ("first ready subtask by rank; no blockers").

## Slots

A slot is a run that needs the pipeline, not a human reviewer: stages `spec`, `plan`, `awaiting_plan_approval`, `dev`, `review`, `complete` and `addressing_review`, plus a launched ticket with no `state.json` yet. `awaiting_plan_approval` holds a slot (it waits for a person, and more work on top of an unapproved plan is not wanted). `done` (PR open, waiting for review), `merged` and `aborted` free it. `max` defaults to 1.

## Flow state

`$(git rev-parse --git-common-dir)/gated-dev/flow/<PARENT>.json`: shared by every worktree, never committed. Runs stay in each worktree's `state.json`; the flow only reads them.

```json
{
  "version": 1,
  "parent": "PROJ-100",
  "startedAt": "2026-11-22T09:00:00Z",
  "updatedAt": "2026-11-22T11:12:00Z",
  "max": 1,
  "tickets": {
    "PROJ-101": {
      "status": "launched",
      "summary": "Add the export endpoint",
      "reason": "first ready subtask by rank; no blockers",
      "launchedAt": "2026-11-22T09:01:00Z",
      "worktree": "/path/to/wt",
      "stage": "dev",
      "prUrl": null,
      "relaunches": 0,
      "staleWarnedAt": null
    },
    "PROJ-104": { "status": "skipped", "reason": "needs a vendor contract", "at": "2026-11-22T09:05:00Z" }
  },
  "picks": [
    { "at": "2026-11-22T09:01:00Z", "key": "PROJ-101", "reason": "first ready subtask by rank; no blockers" }
  ]
}
```

- `status`: `launched`, `merged`, `aborted` or `skipped`. `stage`, `worktree` and `prUrl` are copied from the run on every observation (`flow.py status`, and every poll of `flow.py wait`).
- A run whose `stage` is `merged` or whose PR was merged becomes `merged`; a run in stage `aborted`, or gone after it had a worktree, becomes `aborted` (the ticket is not picked again until `flow.py retry --parent PARENT KEY`).
- `picks` keeps the last 50 decisions.
- Writes are atomic (temp file and rename) and hold a lock file (`<PARENT>.lock`, with the pid) for the write; a lock whose pid is gone is stale.

## Wait outcomes

`flow.py wait` prints one line `{outcome, parent, tickets, at}`:

| Outcome | When | Entries in `tickets` |
| --- | --- | --- |
| `slot-free` | a slot-holding run reached `done`, `merged` or `aborted` | `key`, `status`, `stage`, `prUrl` |
| `lost-watch` | a `done` run, PR open, watch heartbeat older than `flow.lostWatchMinutes` | `key`, `prUrl`, `stage`, `capped`, `relaunches` |
| `merged-orphan` | PR merged but the run is still `done` and its watch is gone | as `lost-watch` |
| `stale` | a slot-holding run unchanged for `flow.staleHours` (once per run) | `key`, `stage`, `idleHours` |
| `error` | `gh` or git failed 5 polls in a row, or the state is unreadable (exit 1) | none; the line has `message` |

At most 3 relaunches per ticket; the next one comes back once with `capped: true` and is then left alone.
