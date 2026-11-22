# Plan: dev tiers (Godzilla, Workhorse, Pawn)

Status: draft, not started. Plugin: `gated-dev-simple-workflow` (→ 0.14.0, or
0.13.0 if it ships before [ticket-modes.md](ticket-modes.md)).

## 1. Goal

Replace the single `ticket-dev` agent with three dev agents of different
weight, and let the main session (the `/ticket` orchestrator) choose which one
implements the plan, fixes review findings and addresses PR feedback.

| Agent (`subagent_type`) | Role | Model | Effort | For |
| --- | --- | --- | --- | --- |
| `gated-dev-simple-workflow:ticket-dev-godzilla` | Senior dev, heavy load | `opus` | `high` | Many steps, cross-cutting changes, tricky logic, migrations, concurrency, performance, anything on the escalation list the plan already decided |
| `gated-dev-simple-workflow:ticket-dev-workhorse` | Mid-level dev, medium load | `sonnet` | `high` | The normal case (what `ticket-dev` does today) |
| `gated-dev-simple-workflow:ticket-dev-pawn` | Junior dev, light load | `haiku` | `medium` | Few, mechanical steps fully spelled out in the plan: copy, config, docs, renames, a test for a known case |

`ticket-dev` is removed (no alias): the plugin has no external callers of it,
and keeping it would leave two names for the workhorse.

## 2. Decisions

**D1. One contract, three agents.** All three keep the current `ticket-dev`
contract unchanged: prompt lines, `MODE=implement|fix-review|fix-pr`,
`Plan-Step:` / `Review-Fix:` / `PR-Fix:` trailers, `dev-report.md`, the
escalation list, gate rules, final line. The orchestrator's checks after the
dev stage (section 7) stay as they are. Only the frontmatter (`name`,
`description`, `model`, `effort`) and a short "Your level" section differ:

- **Godzilla:** may restructure within the planned files and pick the
  approach for a step when the plan leaves it open; still escalates
  everything on the escalation list (binding for every tier).
- **Workhorse:** as `ticket-dev` today.
- **Pawn:** follows the plan literally. Any step that needs a choice the plan
  does not make, a file the plan does not list, or more than a local change
  ends the run with `NEEDS_DECISION` whose `question:` starts with the fixed
  prefix `tier too low: ` (D4). It never guesses.

**D2. The three files must not drift.** Agent files cannot include a shared
file, so the body is duplicated. A test (`test_dev_agents.py`) checks that
the three bodies are identical outside the "Your level" section and the
frontmatter, and that each has the expected `name`, `model` and `effort`.

**D3. The orchestrator chooses the tier, using the planner's advice.**

1. The planner adds a `## Dev tier` section to `plan.md`: one of
   `godzilla | workhorse | pawn` and a reason (step count, how much each
   step leaves open, risk, files touched).
2. The orchestrator decides at H2 and shows the choice in the H2 summary
   ("Dev: workhorse (planner: 6 steps, one schema change already decided)").
   Rules, in order:
   1. config `devTier` other than `auto` wins;
   2. a tier the developer names in the H2 free text wins;
   3. never `pawn` when the plan has gated operations, the diff will touch
      `riskPaths`, or a step is marked as a risk;
   4. otherwise the planner's tier; without one, `workhorse`.
3. The choice goes into `state.json` (`devTier`, `devTierReason`) and is
   printed. No extra question: H2 is already the developer's stop.
4. With [ticket-modes.md](ticket-modes.md): the mode bounds the choice.
   heavy → at least `workhorse`; light → at most `workhorse` (needing
   `godzilla` on a light ticket means the mode was wrong; the planner raises
   the mode instead).

Per stage:

| Dev run | Tier |
| --- | --- |
| `MODE=implement` | `devTier` |
| `MODE=fix-review`, round 1 | `devTier` |
| `MODE=fix-review`, round 2 and later | one tier up (critical findings that survived a round need more weight) |
| `MODE=fix-pr` | decided per round from `pr-feedback-<n>.md`: `pawn` when every `change` item is mechanical (wording, rename, a missing test for a stated case), else `devTier`, at least `workhorse` when any item touches `riskPaths` |

**D4. Promotion instead of failure.** A tier that runs out of its depth is
promoted automatically, once per tier, before the developer is asked. It
works all the way up (`pawn` → `workhorse` → `godzilla`) and in every dev
run: `implement`, `fix-review` and `fix-pr` (decided 2026-11-22):

| Agent result | Action |
| --- | --- |
| `NEEDS_DECISION` with `tier too low: <reason>` | Re-run the same dev stage with the next tier up. No H-point. |
| `verification failed: ...` from `pawn` or `workhorse` | Re-run with the next tier up (it continues from the committed `Plan-Step:` trailers). A second failure, or a failure from `godzilla`, is H6 as today. |
| Any other `NEEDS_DECISION` | H3 as today. The tier does not change. |
| Crash / no marker | The existing single retry (same tier), then H7. |

Each promotion is appended to `state.devTierHistory`
(`{from, to, reason, stage, at}`) and to `state.warnings` with
`stage: "dev-tier"`, so it shows in `--status` but not under "Skipped checks"
in the PR. `godzilla` returning `tier too low` is treated as H3.

**D5. Configuration.** In `.claude/gated-dev.json`:

```json
"devTier": "auto",
"models": { "devGodzilla": "opus", "devWorkhorse": "sonnet", "devPawn": "haiku" }
```

| Key | Default | Meaning |
| --- | --- | --- |
| `devTier` | `auto` | `auto` (D3) or a fixed tier for every dev run. Promotion (D4) still applies. |
| `models.devGodzilla` / `.devWorkhorse` / `.devPawn` | `opus` / `sonnet` / `haiku` | Model passed for each tier (the orchestrator passes `model` explicitly, SKILL.md section 4). |

`models.dev` is removed. A config that still has it stops the run with
"`models.dev` was replaced by `models.devWorkhorse` (and `devGodzilla`,
`devPawn`)", like any other config error.

## 3. Changes

### Agents (`plugins/gated-dev-simple-workflow/agents/`)

1. `ticket-dev.md` → `ticket-dev-workhorse.md` (`git mv`, keep history);
   new name and description, add "Your level".
2. New `ticket-dev-godzilla.md` and `ticket-dev-pawn.md`: copies with their
   frontmatter and "Your level". Pawn's description says it is for
   mechanical steps only.
3. All three: document the `tier too low: ` prefix next to
   `verification failed: ` in "Final line".
4. `ticket-planner.md`: write `## Dev tier` (D3.1) with the criteria from the
   table in section 1.

### Orchestrator (`skills/ticket/SKILL.md`)

1. Intro table: dev row lists the three agents.
2. Section 0: defaults for `devTier` and the three model keys; the
   `models.dev` error.
3. Section 4: "subagent_type from the table" becomes "for dev, the agent of
   the chosen tier (sections 6, 7, 8, 9b)"; model from the tier's key.
   Parse step: handle `tier too low:` (D4).
4. Section 6 (H2): read `## Dev tier`, decide (D3.2), show it, record it.
5. Section 7: tier choice and promotion (D4); H6 only after the top tier.
6. Section 8: tier per fix round (D3 table).
7. Section 9b step 6: tier per PR round.
8. Section 2 (status): print `devTier`, `devTierHistory`.
9. Section 9a: PR body `## Summary` names the tier(s) that wrote the code.

### References and docs

- `references/pipeline-spec.md`: dev row of the stage table, H6 row (after
  promotion), state example with `devTier`, `devTierReason`,
  `devTierHistory`.
- `references/config.md`: D5; remove `models.dev`.
- `scripts/gated_dev/launch/ticket_project.py`: validate `devTier` and the
  `models` keys, including the `models.dev` error (today `models` is only
  checked as a known top-level key).
- README: agents table, configuration, history entry.
- CLAUDE.md: "four stage agents" → spec, planner, three dev tiers, reviewer;
  the `agents/` line.
- `plugin.json`, `marketplace.json`: version, description; bump
  `metadata.version`.

## 4. Tests

- New `tests/test_dev_agents.py`: the three files exist, frontmatter
  (`name`, `model`, `effort`) as in section 1, bodies identical outside
  "Your level", each mentions both fixed prefixes; `ticket-dev.md` is gone.
- Config validation in `ticket_project.py`: `devTier` values, `models` key
  set, the `models.dev` message.
- Existing: `test_no_named_mcp.py` covers the new agent files without
  changes (check it scans `agents/`).

## 5. Manual check

In the private demo repo: a one-line docs ticket (expect `pawn`), a normal
feature (expect `workhorse`), a ticket with a decided schema change (expect
`godzilla`); a pawn run forced onto a step that needs a choice (expect
`tier too low` and an automatic workhorse re-run); a verification failure
on workhorse (expect a godzilla re-run, then H6); a PR feedback round with
only wording changes (expect `pawn`).

## 6. Decided (2026-11-22)

- Pawn runs on `haiku`. The manual check (section 5) must confirm it keeps
  the dev contract (trailers, report, escalation); if it does not, the
  first fix is a tighter "Your level" section, not a different model.
- Promotion is automatic all the way up, for `tier too low` and
  `verification failed`, in every dev mode (D4).

## 7. Open questions

- **O1.** Allow a tier per plan step (pawn for steps 1–3, workhorse for
  step 4)? Not in this version: one dev run per stage keeps the resume rules
  (`Plan-Step:` trailers) simple. Promotion covers most of the need.
