# Plan: `/ticket-flow`, automatic ticket picking from a Jira parent

Status: draft, not started. Plugin: `gated-dev-simple-workflow` (0.10.0 → 0.11.0).

## 1. Goal

Run the subtasks of one Jira parent (an epic or a story with subtasks)
through `/ticket` with no one choosing the next ticket:

```text
/ticket-flow PROJ-100            pick, launch, wait, repeat until nothing is left
/ticket-flow PROJ-100 --once     one pass: fill the free slots, then stop
/ticket-flow PROJ-100 --status   what has been launched, skipped, merged
/ticket-flow PROJ-100 --skip PROJ-104 needs a vendor contract
/ticket-flow PROJ-100 --retry PROJ-104
```

The README lists this as not built ("the parent-based picker, a long-running
driver that needs its own plan"). The source project had it as a Node CLI
(`start / status / resume / skip`). This plan ports the behaviour, not the
code.

### What the driver adds to `/ticket`

| Already in `/ticket` (per ticket) | Added by `/ticket-flow` (per parent) |
| --- | --- |
| Intake, spec, plan, dev, review, PR | Choosing the next ready subtask |
| Jira transitions and comments | Launching its session (via the launcher) |
| PR watch, feedback rounds, merge cleanup (`watch_pr.py`, 9b–9d) | A limit on parallel runs (`max`) |
| | Flow state across tickets: launched, skipped, merged, pick reasons |
| | Restarting a lost PR watch (session closed while the PR is open) |
| | A warning for stalled runs |

The source driver also opened the feedback and cleanup sessions. Here each
ticket session watches its own PR, so the driver only steps in when that
watch is gone (section 5.4).

## 2. Decisions

**D1. The driver is a skill in an interactive session, with a Python helper.**
The source driver was a CLI that ran `claude -p` with named Atlassian tools for
the pick. That conflicts with two binding rules here: the plugin uses *the
session's* Jira tools (no tokens, no client of its own), and shipped files
never name an MCP server or its tools (`tests/test_no_named_mcp.py`). A
headless pick would need `--allowedTools <named jira tools>` or a permission
bypass. As a skill, the driver uses the Jira tools the session already has,
and their permission prompts go through the normal path (and the gate, if
installed).
The split follows the `/ticket` + `watch_pr.py` pattern: judgement and Jira in
the skill, everything deterministic (state, git, `gh`, launching, waiting) in
`scripts/flow.py`, which has tests.

**D2. Waiting uses a background process that exits on an event**, like
`watch_pr.py`: `flow.py wait` polls, and exits with one JSON line when there
is something to do. The session wakes up, acts and starts the wait again.
Closing the session stops the flow; running `/ticket-flow <PARENT>` again
continues it from the saved state.

**D3. Flow state lives in the git common dir**:
`$(git rev-parse --git-common-dir)/gated-dev/flow/<PARENT>.json`. It is shared
by every worktree, never dirties a checkout and is never committed. Runs
themselves stay in each worktree's `state.json` (read, never written, by the
driver).

**D4. The pick is two steps.** A hard filter (status category, exclusions,
`is blocked by` links) is done by the skill on the Jira data and is the same
every time. Then the skill judges what a filter cannot see: a dependency named
only in a description, a ticket that needs a person (meeting, purchase,
contract), the project's `pickRules`. Every pick and every "nothing ready"
writes its reason into the flow state.

**D5. Merged means Done for the pick.** A ticket whose PR this flow saw merged
counts as Done for the blocker check, even when Jira has not caught up.

**D6. A slot is a run that needs the pipeline**, not a human reviewer: stages
`spec` to `complete` and `addressing_review`, plus runs with no
`state.json` yet (just launched). `awaiting_plan_approval` holds a slot: it
waits for a person, and starting more work on top of an unapproved plan is
not wanted. `done` (PR open, waiting for review) frees the slot. `max`
defaults to 1.

**D7. Jira writes stay in `/ticket`.** `/ticket-flow` authorises Jira reads
(search, read issue) and launching sessions, nothing else. The launched
session does the assignment and transitions as today.

**D8. Requires `tracker`.** Without a `tracker` in `.claude/gated-dev.json`
the skill stops with a message. A file-based flow (`--all` order) is not part
of this plan.

## 3. Configuration

New optional top-level key `flow` in `.claude/gated-dev.json`, validated by
`TicketProject.read_config` (unknown sub-keys and wrong types stop with a
message, as for `tracker`). Setting `flow` without `tracker` is a config error.

```json
"flow": {
  "max": 1,
  "jql": "parent = {parent} ORDER BY Rank ASC",
  "pickRules": [
    "prefer the earliest phase or workstream; summaries look like 'P1 WS2: ...'"
  ],
  "pollSeconds": 60,
  "staleHours": 3,
  "lostWatchMinutes": 10,
  "remoteControl": false
}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `max` | `1` | Runs holding a slot at once (D6). 1–10. |
| `jql` | `parent = {parent} ORDER BY Rank ASC` | Candidate query; must contain `{parent}`. The order is the base priority. |
| `pickRules` | `[]` | Extra plain-language rules for the judgement step. |
| `pollSeconds` | `60` | Poll interval of `flow.py wait`. 15–3600. |
| `staleHours` | `3` | A slot-holding run whose `state.json` has not changed for this long is reported once. |
| `lostWatchMinutes` | `10` | A `done` run with an open PR and a watch heartbeat older than this has lost its watch (5.4). |
| `remoteControl` | `false` | Launch sessions with `--remote-control`. |

CLI flags `--max N` and `--once` override per run; `--max` is stored in the
flow state so a continued flow keeps it.

## 4. Flow state

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
    "PROJ-104": { "status": "skipped", "reason": "needs a vendor contract", "at": "..." }
  },
  "picks": [
    { "at": "...", "key": null, "reason": "PROJ-103 blocked by PROJ-101 (In Progress)" }
  ]
}
```

- `status`: `launched` | `merged` | `aborted` | `skipped`. `stage`, `worktree`
  and `prUrl` are copied from the run on every observation.
- `picks` keeps the last 50 decisions, including "nothing ready".
- Writes are atomic (temp file + rename) and hold a lock file
  (`<PARENT>.lock`, pid inside, stale when the pid is gone) so two driver
  sessions for one parent cannot run; the second one stops with a message.

## 5. Behaviour

### 5.1 Start (`/ticket-flow <PARENT> [--max N] [--once] [--dry-run]`)

1. Read the config; stop without `tracker` (D8). Take the lock.
2. Check the Jira tools: read issue and **search by JQL** are required (the
   search is new; `jira.md` section 1 gets a row "Search issues (flow only)").
   Missing: stop, same wording style as `/ticket`.
3. Read the parent issue; stop when it cannot be read. Print its summary.
4. `flow.py status --parent P --json` (observe and save, 5.3). Report what a
   continued flow already has.
5. Fill free slots (5.2) until full or nothing is ready.
6. Nothing launched and nothing holding a slot and nothing waiting for review:
   print the final report and end. `--once`: print the report and end.
   Otherwise start the wait (5.4) and end the turn.

`--dry-run`: steps 1–4, then show what would be picked and the launch plan
(`launch.py --dry-run` output) without launching or saving.

### 5.2 Pick

1. Run `flow.jql` with `{parent}` replaced (all pages).
2. Hard filter, each drop recorded with its reason:
   - status in `tracker.startFrom`, else Jira's To Do category;
   - not in the flow state (launched, merged, aborted, skipped);
   - no run already (`flow.py status` reports runs found by `find_run` for
     keys this flow did not launch, e.g. started by hand: listed, not picked);
   - every `is blocked by` link is Done, or merged in this flow (D5).
3. Judgement on what is left, in query order: drop a ticket whose description
   names an unfinished dependency or that needs a human-only activity; apply
   `pickRules`. Take the first one left.
4. Nothing left: record a `picks` entry with the reason (the most useful
   blocker first) and stop picking.
5. Otherwise `flow.py launch --parent P KEY --summary "<summary>" --reason
   "<why>"`. It refuses when the key already has a run or is in the state, and
   it saves the ticket as `launched` only after the launcher succeeded. A
   failed launch is reported and not retried in this pass.

### 5.3 Observe (`flow.py`, deterministic)

For each ticket with `status: launched`:

- find its run (`find_run`); read `stage`, `prUrl`, `watch.heartbeatAt` and the
  file's mtime;
- `merged` stage, or the PR merged (`gh pr view --json state`): `status:
  merged`;
- `aborted` stage, or no run at all after it had a worktree: `status: aborted`
  (the slot frees; the ticket is not picked again until `--retry KEY`);
- holds a slot per D6.

### 5.4 Wait (`flow.py wait --parent P`, background)

Polls every `pollSeconds` and exits with one JSON line when one of these
happens (first match wins):

| Outcome | When | Skill does |
| --- | --- | --- |
| `slot-free` | a slot-holding run reached `done`, `merged` or `aborted` | 5.2, then wait again |
| `lost-watch` | a `done` run, PR open, heartbeat older than `lostWatchMinutes` | relaunch `/ticket KEY --resume` (restarts the PR watch); at most 3 relaunches per ticket, then report and leave it |
| `merged-orphan` | PR merged but the run is still `done` and its watch is gone | relaunch `--resume` (runs 9d cleanup) |
| `stale` | a slot-holding run unchanged for `staleHours` | notify once per run (`staleWarnedAt`), wait again |
| `error` | `gh`/git fails 5 times in a row, unreadable state | report; `/ticket-flow <PARENT>` continues |

A run sitting in `awaiting_plan_approval` is not stale for this purpose (it
waits for a person on purpose); only the notification hook of its own
session applies.

### 5.5 Status, skip, retry

- `--status`: no lock, no Jira writes; one observe pass and a table: key,
  status, stage, PR, reason; then free slots and the last pick reason.
- `--skip KEY [reason]`: marks a ticket `skipped` (never picked); a running
  ticket is only marked, its session is not touched.
- `--retry KEY`: removes `skipped`/`aborted` so the ticket can be picked again.

### 5.6 Notifications

The driver session notifies (`hooks/notify.py`, explicit mode) on: nothing
ready while nothing runs (flow finished or blocked), `stale`, a launch failure,
and the third failed relaunch. Launched sessions keep `TICKET_FLOW_KEY` as
today.

## 6. Files

| File | Change |
| --- | --- |
| `skills/ticket-flow/SKILL.md` | New skill: sections 5.1–5.6, the stop points, the authorisation (D7). |
| `skills/ticket/references/flow.md` | Pick rules and state reference (5.2, 4), read by the skill. |
| `scripts/flow.py` | Entry stub, like `launch.py`. |
| `scripts/gated_dev/flow/` | `state.py` (`FlowState`: load, save, lock), `observer.py` (`FlowObserver`), `waiter.py` (`FlowWaiter`), `cli.py` (`FlowCli`: `status`, `launch`, `skip`, `retry`, `wait`). One class per file. |
| `scripts/gated_dev/launch/launcher.py` | `launch_ticket(..., summary=None)`: a summary from the caller titles a tracker ticket with no `ticket.md` (today it gets the plain key). |
| `scripts/gated_dev/launch/ticket_project.py` | `flow` in `CONFIG_KEYS`, `_read_flow` validation; `flow` without `tracker` is an error. |
| `skills/ticket/references/config.md` | `flow` key. |
| `skills/ticket/references/jira.md` | Section 1: search capability (flow only); section 8: what `/ticket-flow` authorises. |
| `README.md` | Usage section "Running a whole parent", the "Not built" line, design history entry. |
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | 0.11.0, description, `metadata.version`. |
| `CLAUDE.md` | The plugin table and the gated-dev section mention `/ticket-flow`. |

## 7. Work packages (one commit each)

**F1. Flow core.** `gated_dev/flow/state.py`, `observer.py` and their tests:
state round trip, atomic write, lock (held, stale pid, second driver),
observation of every stage, merged via `gh`, run gone → aborted, slot count per
D6, keys with runs this flow did not launch.

**F2. Wait and CLI.** `waiter.py`, `cli.py`, `scripts/flow.py`, tests with the
fake runner and clock: each outcome of 5.4, first-match order, 5 failures →
`error`, `stale` reported once, relaunch cap, `launch` refusing an existing
run, `--dry-run` writing nothing, usage errors.

**F3. Launcher and config.** `summary` parameter, `flow` validation, tests in
`test_launch_units.py` / `test_launch_cli.py` (valid config, each invalid
sub-key, `flow` without `tracker`).

**F4. Skill and references.** `skills/ticket-flow/SKILL.md`, `flow.md`,
`config.md`, `jira.md`. `test_no_named_mcp.py` already scans every shipped
`.md`; add a test that the skill's `flow.py` subcommands match `FlowCli`.

**F5. Docs and release.** README, CLAUDE.md, versions, `claude plugin
validate .`, `uv run pytest`, `uv run ruff check .`.

**F6. Acceptance (manual).** Demo repo and a sandbox Jira project, never a
real team project. A parent with 4 subtasks: one blocked by another, one that
needs a person, one dependency named only in a description. Check: the pick
order and reasons, `max 1` and `max 2`, plan approval holding a slot, PR open
freeing it, merge unblocking the blocked one, closing a ticket session with an
open PR → `lost-watch` relaunch, `--skip`, `--status`, stopping the driver
and continuing it, a second driver refused by the lock, `--dry-run`.

## 8. Out of scope

- Trackers other than Jira; a file-based flow.
- Creating, editing or transitioning issues from the driver.
- Running headless (`claude -p`) or from cron; the driver needs an open session.
- Merging PRs or requesting reviews.
- Several parents in one driver session (run one session per parent).

## 9. Open questions

1. Should `done` (PR waiting for review) hold a slot as an option
   (`flow.countOpenPrs`)? Teams with slow reviews may want to cap open PRs.
2. Should the driver move the parent issue (To Do → In Progress at the first
   launch, Done when every subtask is merged)? Default here: no (D7).
3. Is 3 the right relaunch cap for a lost watch, and should a relaunch ask
   first instead (it opens a tab)?
