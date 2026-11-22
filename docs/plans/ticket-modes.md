# Plan: pipeline modes for `/ticket` (heavy, medium, light)

Status: draft, not started. Plugin: `gated-dev-simple-workflow` (0.12.5 → 0.13.0).
Related: [dev-tiers.md](dev-tiers.md) (feature 2, independent; section 9 below
says how the two fit together).

## 1. Goal

Today every ticket runs the full pipeline: spec → plan → dev → review, with
the session model the developer happened to start. Small tickets pay for
stages they do not need. A ticket should run in one of three modes, and the
main session (the `/ticket` orchestrator, or the `/ticket-flow` driver for
subtasks of a Jira parent) decides which one.

| Mode | Stages | Session model | Meant for |
| --- | --- | --- | --- |
| `heavy` | spec → plan → dev → review | Opus | Unclear or cross-cutting tickets, schema, auth, security, infra, new dependencies |
| `medium` | plan → dev → review | Sonnet | Clear tickets of normal size |
| `light` | plan → dev | Sonnet | Small, well-specified changes in one area (copy, config, docs, a contained bug fix) |

What does **not** change in any mode (binding, see CLAUDE.md and the README
history):

- Plan approval (H2) is always a stop point. Light mode still stops at H2.
- The escalation list (`NEEDS_DECISION`, pipeline-spec §4), gate handling,
  scope checks, H6/H7, commit, push, PR, PR watch, merge cleanup.
- Stage agents stay tracker-free and file-based.

## 2. Decisions

**D1. The mode is decided once, at kickoff, after the ticket is read.**
Light and medium skip the spec stage, so the decision must come before it.
Inputs: `ticket.md` (title, text, length, number of acceptance criteria),
with a tracker also the issue type and labels from the front matter, the
`riskPaths` and `escalationExtra` of the config, and `modeRules` (D5). The
orchestrator writes the choice and a one-line reason to `state.json`
(`mode`, `modeReason`) and prints it. It does **not** ask: the developer can
still stop or redirect the run at H2.

**D2. Decision rules, in order** (documented in a new
`skills/ticket/references/modes.md`):

1. An explicit `--mode heavy|medium|light` (from the developer or the flow
   driver) wins.
2. Config `mode` other than `auto` wins.
3. `heavy` when the ticket touches anything on the escalation list (data
   model or schema, auth, security, tenant isolation, secrets, new
   dependency or service, recurring cost), names paths that match
   `riskPaths`, has open questions or missing acceptance criteria, or spans
   several areas of the repo.
4. `light` only when all hold: one area, a clear expected result, no item of
   rule 3, and the change is small (the ticket names a few files or a single
   behaviour).
5. Otherwise `medium`.
6. When unsure between two modes, take the heavier one.

**D3. A mode can be raised during the run, never lowered.**

| When | Raise | Effect |
| --- | --- | --- |
| Planner finds the ticket is bigger or riskier than the mode assumed (new `## Mode` line in `plan.md`: `raise to heavy: <reason>`) | `light`/`medium` → `heavy` | Before H2 only: run the spec stage, then plan again with the spec. |
| Planner flags it, or the developer asks at H2 | `light` → `medium` | Review stage is added; nothing re-runs. |
| The dev diff touches `riskPaths` (checked where section 8 picks the reviewer model) | `light` → `medium` | Review runs (on `models.reviewRisk`). |
| The developer says so at H2 (free text "use heavy" / "add a review") | any upward | As above. |

Every raise is recorded in `state.decisions` and `decisions.md`
(`stage: mode`) and in `state.modeHistory`.

**D4. The session model is set when the session starts; a running session
cannot change its own model.** So:

- Launched sessions (`launch.py`, `flow.py launch`) start with
  `claude --model <session model of the mode>` and pass `--mode` in the
  `/ticket` prompt. The launcher decides the mode only when the caller gave
  one; otherwise it starts the default session model and the session
  decides (D1).
- A session started by hand keeps its model. When the decided mode wants a
  stronger session model than the one running (heavy in a Sonnet session),
  the orchestrator asks (`AskUserQuestion`, decided 2026-11-22):
  **Stop and restart on Opus (recommended)**: `state.json` is written with
  the mode, the orchestrator prints
  `claude --model <model> "/ticket <KEY> --resume"` and ends the turn; the
  resumed session uses the recorded mode. **Continue here**: recorded in
  `state.decisions` (`stage: mode`) and `state.warnings`, the run goes on;
  the stage agents still get their `model` explicitly (SKILL.md section 4).
  The same question comes when D3 raises the mode mid-run past the running
  session's model. A weaker mode in a stronger session (light in Opus) is
  not asked about.

**D5. Configuration** (`.claude/gated-dev.json`, validated in the skill and in
`ticket_project.py`):

```json
"mode": "auto",
"modes": {
  "heavy":  { "session": "opus" },
  "medium": { "session": "sonnet" },
  "light":  { "session": "sonnet" }
},
"modeRules": ["anything under packages/billing is at least medium"]
```

| Key | Default | Meaning |
| --- | --- | --- |
| `mode` | `auto` | `auto` (the session decides, D2) or a fixed mode for every ticket. |
| `modes.<mode>.session` | as in section 1 | Session model the launcher starts for that mode. |
| `modeRules` | `[]` | Extra plain-language rules for D2, like `flow.pickRules`. |

Stage sets per mode are fixed, not configurable: a configurable stage list
would make the H-points and the state machine depend on the project.

**D6. Without a spec, the plan carries the acceptance criteria.** In medium
and light mode the planner reads `ticket.md` instead of `spec.md` and adds a
`## Acceptance criteria` section to `plan.md` (testable, taken from the
ticket; a missing or unclear criterion is a `NEEDS_DECISION` with
`stage: plan`, which also takes over H1's role). Dev and reviewer read the
criteria from `spec.md` when it exists, else from `plan.md`.

## 3. Changes to `skills/ticket/SKILL.md`

1. Intro table: add a "Modes" column or a short paragraph pointing to
   `references/modes.md`.
2. Section 0: defaults for `mode`, `modes`, `modeRules`; validate them.
3. Section 1: new flag `--mode heavy|medium|light`; allowed together with no
   flag (new run) only. With `--resume` the recorded mode is used and a
   `--mode` that differs is refused with a message.
4. Section 3: new step after step 1 (ticket file): **Mode** (D1/D2). Write
   `mode`, `modeReason`, `modeHistory: []` into `state.json` in step 6.
   After step 6, the session-model question of D4 when the running model
   is weaker than the mode's.
   Step 10 continues with the spec stage in heavy mode and with the plan
   stage otherwise (stage `plan`).
5. Section 4 prompt: new line `MODE_PIPELINE=heavy|medium|light` for the
   planner, dev and reviewer (name differs from the dev agent's `MODE=` on
   purpose).
6. Section 6 (plan, H2): read the `## Mode` line of `plan.md`; apply D3.
   H2 shows the mode and its reason; the free text may raise it.
7. Section 8 (review): skipped in light mode, unless D3 raised it. Light
   mode goes from dev straight to section 9a.
8. Section 9b (PR feedback): light mode runs `fix-pr` and the verification
   but no reviewer; the summary comment says so.
9. Section 9a: PR body gets a `Mode: <mode> (<reason>)` line under
   `## Summary`; light mode adds "No review stage ran" under
   `## Skipped checks`.
10. Section 2 (status): print `mode`, `modeReason`, `modeHistory`.
11. Section 9 (resume): re-enter with the recorded mode.

## 4. Changes to the stage agents

| Agent | Change |
| --- | --- |
| `ticket-planner` | Contract: `MODE_PIPELINE=`. Without `spec.md` (medium, light) read `ticket.md` and write `## Acceptance criteria`. Always write `## Mode` with `keep` or `raise to <mode>: <reason>`. |
| `ticket-dev` | Read acceptance criteria from `spec.md`, else `plan.md`. Nothing else. |
| `ticket-reviewer` | Same as dev for the criteria. |
| `ticket-spec` | Unchanged (heavy only). |

## 5. Changes to `/ticket-flow` and the launcher

1. `skills/ticket-flow/SKILL.md` and `references/flow.md`: after the pick,
   the driver decides the mode with the rules of D2 from the issue it just
   read, and passes it: `flow.py launch ... --mode <mode> --reason "<pick
   reason>; mode <mode>: <reason>"`. `--status` shows the mode per ticket.
2. `scripts/gated_dev/flow/cli.py`: `--mode` option for `launch`; stored on
   the ticket in the flow state (`FlowState.add_launched(..., mode=)`).
3. `scripts/gated_dev/launch/cli.py`: `--mode heavy|medium|light` (applies to
   all keys of the call), and `--mode` in `ALLOWED_ARGS` of the `/ticket`
   prompt.
4. `scripts/gated_dev/launch/terminal.py` `build_shell_command`: new
   `model` argument → `claude --model <model> --name ...`; model must be one
   of a fixed set of aliases (`opus`, `sonnet`, `haiku`) or a
   `claude-[a-z0-9.-]+` id, so nothing unsafe reaches the shell line.
   Orca launch path the same.
5. `scripts/gated_dev/launch/ticket_project.py`: add `mode`, `modes`,
   `modeRules` to `CONFIG_KEYS`, validate types and values.
6. `skills/launch/SKILL.md`: document `--mode`; dry run shows the model.
7. Resume launches (`/ticket KEY --resume`) start with the session model of
   the recorded mode (read from the run's `state.json`).

## 6. Documentation

- New `skills/ticket/references/modes.md`: the table of section 1, D2, D3,
  D4.
- `references/pipeline-spec.md`: stage table per mode, `mode` fields in the
  state example (§7), H2 row mentions the mode.
- `references/config.md`: the keys of D5.
- README: user-facing description and an entry in "Design decisions and
  history" when done.
- `plugin.json`, `marketplace.json`: version 0.13.0, description mentions
  modes; bump `metadata.version`.

## 7. Tests

Markdown has no tests; the Python parts do:

- `test_launch_units.py`: `build_shell_command` with `model` (alias, full
  id, rejected values with quotes or spaces), `--mode` in the prompt.
- `test_launch_cli.py`: `--mode` parsing, dry run output shows model and
  mode, resume picks the recorded mode's model.
- `test_flow_units.py` / `test_flow_wait.py`: `launch --mode` stored in the
  state; `status` output carries it.
- Config validation: unknown mode, `modes` with an unknown mode or key, wrong
  types.
- `test_flow_skill.py`: the skill mentions `--mode` on launch (extend the
  existing text checks).

## 8. Manual check

In the private demo repo: one ticket per mode started by hand, one Jira
parent through `/ticket-flow` with a mix of small and large subtasks, a
light ticket whose diff touches `riskPaths` (review gets added), a planner
raise to heavy before H2, and `--resume` of a light run.

## 9. With feature 2 (dev tiers)

Both features stand alone. Together, the mode gives the dev tier a starting
point (dev-tiers.md, D3): heavy → `workhorse` or `godzilla`, medium →
`workhorse`, light → `pawn` or `workhorse`. The mode never picks `godzilla`
for a light ticket: if a light ticket needs it, the mode was wrong and D3
raises it first.

## 10. Decided (2026-11-22)

- A hand-started session weaker than its mode asks the developer: restart
  on the stronger model or continue (D4).
- Light mode does **not** get a review stage because the plan has gated
  operations. Gated calls still stop at the gate and are listed at H2; only
  `riskPaths` in the diff or an explicit raise (D3) adds a review.

## 11. Open questions

- **O1.** Session model for medium and light: Sonnet as asked; should a
  project be able to put light on Haiku via `modes.light.session`? (The
  config allows it; the default stays Sonnet.)
