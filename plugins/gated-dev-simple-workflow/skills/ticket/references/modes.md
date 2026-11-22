# Modes: heavy, medium, light

How much of the pipeline a ticket runs. Used by the orchestrator
(`skills/ticket/SKILL.md`), the planner (`ticket-planner`) and the flow driver
(`skills/ticket-flow/SKILL.md`). The keys `mode`, `modes` and `modeRules` are
described in [config.md](config.md#modes); H-points, `NEEDS_DECISION` and
the stage table are in [pipeline-spec.md](pipeline-spec.md).

## 1. The modes

| Mode | Stages | Session model (`modes.<mode>.session` default) | Meant for |
| --- | --- | --- | --- |
| `heavy` | spec → plan → dev → review | `opus` | Unclear or cross-cutting tickets; data model or schema, auth, security, infra, new dependencies |
| `medium` | plan → dev → review | `sonnet` | Clear tickets of normal size |
| `light` | plan → dev | `sonnet` | Small, well-specified changes in one area (copy, config, docs, a contained bug fix) |

Kickoff and complete (push, PR, PR watch, merge cleanup) run in every mode.
The stage set of a mode is fixed; a project cannot configure it. Modes are
ordered `light` < `medium` < `heavy`; "heavier" and "raise" refer to this
order.

What each mode changes, and nothing else:

| | heavy | medium | light |
| --- | --- | --- | --- |
| Spec stage, `spec.md` | yes | no | no |
| Planner reads | `spec.md` | `ticket.md` | `ticket.md` |
| Acceptance criteria live in | `spec.md` | `plan.md` (§7) | `plan.md` (§7) |
| H1 (spec question) | yes | no; the planner's `NEEDS_DECISION` (`stage: plan`, asked as H3) takes its role | as medium |
| Review stage (section 8 of SKILL.md), H5 | yes | yes | no, unless raised (§5, §8) |
| Reviewer in a PR feedback round (SKILL.md 9b) | yes | yes | no, unless raised (§8) |
| Initial `stage` in `state.json` | `spec` | `plan` | `plan` |
| Files committed at plan approval | `ticket.md`, `spec.md`, `plan.md`, `decisions.md` | `ticket.md`, `plan.md`, `decisions.md` | as medium |

Every stage prompt to the planner, dev agent and reviewer carries the line
`MODE_PIPELINE=heavy|medium|light`. The name differs on purpose from the dev
agent's `MODE=implement|fix-review|fix-pr`, which is unrelated.

## 2. What never changes

In every mode:

- **H2 is a stop.** No product code is written and no gated action is
  attempted before the developer approves the plan. Light mode stops at H2
  too.
- The escalation list and `NEEDS_DECISION` ([pipeline-spec.md §4](pipeline-spec.md#4-important-decisions-and-needs_decision)),
  H3, H4, H6 and H7, scope checks, and gate handling: a gate prompt or denial
  is a checkpoint, never something to work around.
- Commit, push (never forced), PR, PR watch, PR feedback rounds and merge
  cleanup.
- Stage agents stay file-based and tracker-free. Tracker steps
  ([jira.md](jira.md)) run at the same events; an event of a stage that does
  not run in the mode (`spec-done` outside heavy, `review-done` in light) does
  not happen.
- Each stage agent gets its `model` from `models` explicitly, whatever the
  session model is.

## 3. When the mode is decided (D1)

1. Once per run, at kickoff, after the ticket file is read (SKILL.md
   section 3, step 1) and before any stage runs. Medium and light skip the
   spec stage, so the decision cannot come later.
2. The orchestrator writes `mode` and a one-line `modeReason` into
   `state.json` (written in kickoff step 6, §9) and prints
   `Mode: <mode> (<modeReason>)`.
3. It does **not** ask the developer about the mode. The developer can stop or
   redirect the run at H2 (§5).
4. After kickoff the mode can only be raised (§5), never lowered and never
   decided again. A resumed run uses the recorded mode (§10).

## 4. Decision rules (D2)

Apply in order; the first rule that decides wins.

1. **Explicit `--mode heavy|medium|light`** on `/ticket` (given by the
   developer, the launcher or the flow driver). `modeReason`:
   `--mode <mode> given at start`.
2. **Config `mode`** other than `auto`. `modeReason`: `config mode <mode>`.
3. **`heavy`** when any of these holds for the ticket:
   - it touches an item of the escalation list (data model or schema, auth,
     security, tenant isolation, secrets, a new dependency, service or cloud
     resource, recurring cost) or of `escalationExtra`;
   - it names paths that match `riskPaths`;
   - it has open questions, or its acceptance criteria are missing or not
     testable;
   - it spans several areas of the repository (more than one app, package or
     top-level directory, or more than one layer such as UI, API and data).
4. **`light`** only when all of these hold: one area; a clear expected
   result; no item of rule 3; the change is small (the ticket names a few
   files or a single behaviour).
5. Otherwise **`medium`**.
6. **When unsure between two modes, take the heavier one.**

`modeRules` (config) are extra plain-language rules applied together with
rules 3 to 5. A rule that sets a floor ("anything under packages/billing is
at least medium") rules out the lighter modes; a rule never makes a ticket
lighter than rule 3 demands. Rules 1 and 2 are not subject to `modeRules`.

Inputs to rules 3 to 6: `ticket.md` (title, text, length, number of
acceptance criteria), with a tracker also the issue type and labels from its
front matter, and the config's `riskPaths`, `escalationExtra` and
`modeRules`. The reason names the rule that decided, for example
`light: one area (apps/web copy), clear result, one file` or
`heavy: adds a database migration`.

**Who decides.** `/ticket` started by hand: the orchestrator, with these
rules. `/ticket-flow`: the driver decides with rules 2 to 6 from the issue it
just read (see [flow.md](flow.md)) and always launches with `--mode`, so the
session applies rule 1. `launch` without `--mode`: the session decides.

## 5. Raising the mode (D3)

A mode can be raised during the run, never lowered. These are the only
raises:

| # | When | By (`modeHistory.by`) | Raise | Effect |
| --- | --- | --- | --- | --- |
| R1 | The planner's `## Mode` line (§6) says `raise to heavy: <reason>` | `planner` | `light`/`medium` → `heavy` | Before H2: set `stage: "spec"`, run the spec stage, then the planner again with `spec.md`, then H2. |
| R2 | The planner's `## Mode` line says `raise to medium: <reason>` | `planner` | `light` → `medium` | The review stage is added; nothing re-runs. H2 follows as usual. |
| R3 | The developer asks at H2 in free text ("use heavy", "add a review") | `developer` | any upward | To `heavy`: as R1 (other change requests in the same text go to the planner under `FEEDBACK:`). To `medium` without other change requests: nothing re-runs, H2 is asked again showing the new mode; with change requests: re-plan as usual. |
| R4 | After dev in light mode, the diff touches `riskPaths` (the check SKILL.md section 8 uses to pick the reviewer model) | `riskPaths` | `light` → `medium` | The review stage runs, on `models.reviewRisk`. |

Rules for every raise:

1. A raise to `heavy` is possible only before H2 is approved (R1, R3). After
   approval only R4 exists.
2. A request to lower the mode (at H2, or a planner line naming a lighter or
   the same mode) is not applied: the orchestrator says that a mode is never
   lowered and goes on with the current mode. A developer who wants a
   lighter run aborts and starts a new run with `--mode`.
3. Each raise is recorded in three places before anything else happens: an
   entry in `state.modeHistory` (§9), an entry in `state.decisions` with
   `stage: "mode"`, and a `## <ISO time> (mode)` entry in `decisions.md`
   (committed alone once the plan is approved, as SKILL.md section 4 says for
   every decision). `mode` and `modeReason` are updated to the new mode and
   the raise's reason.
4. If the new mode's session model is stronger than the running one, the
   session-model question of §6 is asked right after the raise is recorded.
5. Gated operations in the plan never raise the mode (§8).

## 6. Session model (D4)

A running session cannot change its own model. The model is set when the
session starts.

**Launched sessions** (`launch.py`, `flow.py launch`): with a mode, the
launcher starts `claude --model <modes.<mode>.session>` and passes
`/ticket <KEY> --mode <mode>`. Without a mode it starts without `--model`
(the session decides the mode, §4). A resume starts on the session model of
the mode recorded in `state.json` and passes no `--mode`.

**Hand-started sessions** keep their model. Strength order:
`haiku` < `sonnet` < `opus`; a `claude-...` id counts as the family it names
(`claude-sonnet-...` is `sonnet`). The running model is the one the session's
own instructions name. When the mode's session model is stronger than the
running one, or either cannot be placed in the order, the orchestrator asks
(`AskUserQuestion`):

- **Stop and restart on `<model>` (recommended).** Record the answer in
  `state.decisions` (`stage: "mode"`, §9), make sure `state.json` holds the
  mode and the stage to re-enter, print the worktree path and the exact
  command, then end the turn without spawning anything:

  ```
  cd '<worktree>' && claude --model <model> "/ticket <KEY> --resume"
  ```

  `<model>` is `modes.<mode>.session`. The resumed session uses the recorded
  mode (§10).
- **Continue here.** Record the answer in `state.decisions` (`stage: "mode"`)
  and append a warning to `state.warnings` (§9); the run goes on in this
  session. Stage agents still get their `model` explicitly.

When it is asked:

1. At the end of kickoff: after SKILL.md section 3 step 9 (setup and the
   `started` events have run), before the first stage. Asking here, not
   right after step 6, means a restarted session resumes into the first
   stage with nothing of kickoff left undone.
2. After a raise (§5 rule 4). The stage to re-enter is set before the
   question: `spec` for a raise to heavy, `awaiting_plan_approval` for R2 and
   R3 to medium, `review` for R4.
3. On `--resume` in a session weaker than the recorded mode's, unless a
   **Continue here** for that mode is already recorded in `state.decisions`.

A weaker mode in a stronger session (light in an `opus` session) is never
asked about.

## 7. Acceptance criteria without a spec (D6)

In medium and light mode there is no `spec.md`. The planner:

1. reads `ticket.md` instead of `spec.md`;
2. adds a `## Acceptance criteria` section to `plan.md`: testable criteria
   taken from the ticket;
3. raises `NEEDS_DECISION` with `stage: plan` for a criterion that is missing
   or unclear. This takes over H1's role; the orchestrator asks it as H3.

The dev agent and the reviewer read the acceptance criteria from `spec.md`
when it exists, otherwise from `plan.md`. After R1 the spec exists and the
re-plan takes the criteria from it.

### The `## Mode` section of `plan.md`

The planner always writes it, in every mode. Its first non-empty line is
exactly one of:

```
keep
raise to medium: <one-line reason>
raise to heavy: <one-line reason>
```

In heavy mode it is always `keep`. A line that names the current or a lighter
mode counts as `keep` (§5 rule 2). A missing section or another line counts
as `keep`, and H2 says that the planner gave no valid mode line.

## 8. Light mode and review

Light mode has no review stage. Decided 2026-11-22: the review is added only
by

- R4, `riskPaths` in the diff, or
- an explicit raise (R2, R3).

Gated operations in the plan do **not** add a review: gated calls still stop
at the gate (H4) and are listed in the `## Gated operations` table at H2.

For a light run that is not raised:

- after dev the run goes from SKILL.md section 7 straight to section 9a;
- the PR body lists `No review stage ran` under `## Skipped checks`;
- a PR feedback round (SKILL.md 9b) runs the dev agent with `MODE=fix-pr` and
  the verification, but no reviewer; the round's summary comment says that no
  review ran. Before skipping the reviewer, the round runs the R4 check on
  the branch diff; a hit raises to medium and the reviewer runs in that round
  and in later ones.

## 9. Records

### `state.json`

Written at kickoff step 6 and kept by every writer:

```json
{
  "mode": "light",
  "modeReason": "light: one area (apps/web copy), clear result, one file",
  "modeHistory": [
    {
      "from": "light",
      "to": "medium",
      "by": "riskPaths",
      "stage": "review",
      "reason": "diff touches .github/workflows/ci.yml",
      "at": "2026-11-22T10:15:00Z"
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `mode` | Current mode: `heavy`, `medium` or `light`. |
| `modeReason` | One line: why the run has its current mode (the decision of §4, or the reason of the last raise). |
| `modeHistory` | Raises in order, `[]` at kickoff. `from`, `to`: modes. `by`: `planner`, `developer` or `riskPaths`. `stage`: the `stage` the run enters for the raise (§6, point 2). `reason`: one line. `at`: ISO-8601. |

A `state.json` without `mode` (a run started before modes existed) counts as
`heavy`, the full pipeline it was started with.

Entries in the existing lists (shapes of [pipeline-spec.md §7](pipeline-spec.md#7-state-and-resume)):

| Event | List | Entry |
| --- | --- | --- |
| Raise | `decisions` | `{"stage": "mode", "question": "raise mode <from> to <to> (<by>)", "answer": "<reason>", "at"}` |
| Session-model question | `decisions` | `{"stage": "mode", "question": "session model <running> is weaker than <model> for mode <mode>", "answer": "restart on <model>" or "continue here", "at"}` |
| **Continue here** | `warnings` | `{"stage": "mode", "command": "session model", "reason": "<mode> run continues on <running>; the mode starts <model>", "at"}` |

Each `decisions` entry gets the matching `## <ISO time> (mode)` entry in
`decisions.md`. A `warnings` entry with `stage: "mode"` is listed under
`## Skipped checks` in the PR like any other warning.

### Where the mode is shown

| Where | What |
| --- | --- |
| Kickoff | `Mode: <mode> (<modeReason>)` |
| Status (`--status`) | `mode`, `modeReason`, every `modeHistory` entry |
| H2 | The mode and its reason, and any raise the planner made |
| PR body | `Mode: <mode> (<modeReason>)` as a line under `## Summary`; light adds `No review stage ran` under `## Skipped checks` |

## 10. Resume

`--resume` re-enters the recorded stage with the recorded `mode`.

1. A `--mode` equal to the recorded mode is accepted and changes nothing.
   A `--mode` that differs is refused with a message naming the recorded
   mode; nothing is changed. A raise happens only through §5.
2. `--mode` is allowed with no flag (a new run) and with `--resume`, never
   with `--status` or `--address-review`.
3. The session-model question follows §6, point 3.
