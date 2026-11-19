---
name: ticket
description: Run a ticket file through the spec, plan, dev, review and PR pipeline with one subagent per stage, in its own git worktree. Use when the user invokes /ticket <KEY> (optionally with --resume or --status), or says "start working on ticket <KEY>", "pick up <KEY>", "resume <KEY>" or "status of <KEY>". The ticket is a Markdown file (docs/tickets/<KEY>/ticket.md by default) or a description the user pastes.
---

# /ticket: ticket pipeline orchestrator

You are the orchestrator. You run in the main session, never write product code yourself, and drive four stage subagents through one ticket:

| Stage | Agent (`subagent_type`) | Writes |
| --- | --- | --- |
| spec | `gated-dev-simple-workflow:ticket-spec` | `spec.md` |
| plan | `gated-dev-simple-workflow:ticket-planner` | `plan.md` |
| dev | `gated-dev-simple-workflow:ticket-dev` | commits, `dev-report.md` |
| review | `gated-dev-simple-workflow:ticket-reviewer` | `review.md` |

The pipeline is file-based: the ticket is `ticket.md`, and every stage reads and writes files in the ticket directory. There is no issue tracker. The design (interaction points H1 to H7, the `NEEDS_DECISION` protocol, stages, state file) is in `references/pipeline-spec.md`; the per-project settings are in `references/config.md`. Read the section you are acting on instead of working from memory.

Rules that hold everywhere:

- Every stop for the developer goes through `AskUserQuestion`, recommended option first (the H-points). Calls that an approval gate stops use the normal permission prompt (H4); you do not handle those.
- Spawn every stage subagent in the **foreground** (never `run_in_background`) and pass `model` explicitly (section 4).
- Never launch, restart or stop apps, dev servers or Docker. If something needs them and they are down, that is an infrastructure blocker (H6).
- Never route around an approval gate, and never run a gated operation that the approved plan does not list. Do not edit product files yourself.
- Keep `state.json` current: after every transition set the new `stage` and `updatedAt` (ISO-8601). Re-read it before every write and write the whole file.
- `state.json` is never committed. Never stage it, and never run a bare `git add -A`: when staging everything, use `git -C <wt> add -A -- . ':(exclude)<ticketsDir>/*/state.json'`.
- Commit trailer: end every commit message you write with the `Co-Authored-By` attribution line that your session's instructions specify for commits. Do not hard-code a model name; if the session specifies no attribution, add none. "The trailer" below means this line.
- Formatting: "format `<files>`" below means: run `<formatCommand> <files>` in the worktree when `formatCommand` is configured; otherwise do nothing.

## 0. Configuration and host

1. `<session-root>` is the top level of the checkout this session started in (`$CLAUDE_PROJECT_DIR`, else `git rev-parse --show-toplevel`). `<root>` is the main checkout: the first `worktree` entry of `git worktree list --porcelain`.
2. Read `<session-root>/.claude/gated-dev.json` if it exists (all keys optional; see `references/config.md`). Invalid JSON or an unknown key: report it and stop; never guess. Defaults: `ticketsDir` `docs/tickets`, `keyPattern` `^[A-Za-z][A-Za-z0-9._-]*$`, `baseBranch` unset, `setupCommand` unset, `formatCommand` unset, `riskPaths` (section 8), `escalationExtra` `[]`, `models` `{spec: sonnet, plan: opus, dev: sonnet, review: sonnet, reviewRisk: opus}`.
3. Host: `orca` when `TERM_PROGRAM=Orca`, or `ORCA_TERMINAL_HANDLE` is set and `TERM_PROGRAM` is not `iTerm.app`; `iterm` when `TERM_PROGRAM=iTerm.app` or `ITERM_SESSION_ID` is set; otherwise `plain`. Only `orca` changes how worktrees are created and removed; `iterm` and `plain` use git directly.

## 1. Arguments

1. Take the key from the user's text. It must match `keyPattern` and must not contain `/` or `..`; otherwise ask for it and stop.
2. Flags: `--resume` ("resume <KEY>"), `--status` ("status of <KEY>"). At most one. No flag means a new run ("start working on", "pick up").
3. Find an existing run: in `git worktree list --porcelain`, look for a worktree whose branch matches `refs/heads/<KEY>/*`. Its state file is `<wt>/<ticketsDir>/<KEY>/state.json`. If several match, keep the one whose `stage` is not `aborted`; if that still leaves zero or more than one, ask which to use. Set `TICKET_DIR=<wt>/<ticketsDir>/<KEY>`.
4. Cases:
   - `--status`: no worktree or no state file: report "no state found for <KEY>", change nothing, stop. Otherwise section 2.
   - `--resume`: no worktree or no state file: say there is nothing to resume and offer a new run. Otherwise section 9.
   - No flag, state exists: ask Resume (recommended) · Restart. Restart asks once more for confirmation, sets the old run to `aborted` (section 10), and runs kickoff with a fresh slug suffix (`-2`, `-3`, ...) so the branch differs. Never delete a worktree or branch.
   - No flag, no state: kickoff (section 3).

## 2. Status (read-only)

Read `state.json` and print: ticket, title, stage (and `reviewRound`), branch, worktree, base branch, PR URL if any, the number of recorded decisions with the last question, every entry of `warnings`, and the paths of `ticket.md`, `spec.md`, `plan.md`, `dev-report.md` and `review.md` that exist. "Open questions" means: stage `awaiting_plan_approval` (the plan waits for approval), or the unresolved `## Open questions` of `spec.md` when the stage is `spec`. Write nothing, spawn nothing.

## 3. Kickoff

Steps 1 to 5 stop with a clear message on any failure and leave nothing behind. Once the worktree exists, a failure never removes it: keep the worktree and branch, follow H6 or the abort rules, and record what happened in `state.json`.

1. **Ticket file.** Look for `<session-root>/<ticketsDir>/<KEY>/ticket.md`.
   - It exists: use it. If the user also pasted a description, ask Use the file (recommended) · Replace it with the pasted text.
   - It does not exist and the user's message carries a description (anything beyond the key and flags): this text is the ticket. Write it to that path, with a `# <title>` first line (the user's title, or a short one you derive) followed by the text verbatim.
   - Neither: tell the user to create `<ticketsDir>/<KEY>/ticket.md` or to paste a description with the command, and stop.

   An empty file, or one with no `# ` heading, is not a ticket: say so and stop. Read the optional YAML front matter (`---` block at the top): `base:` (a branch name) is the only key the orchestrator uses. The title is the first `# ` heading.
2. **Base branch.** The first that applies: front matter `base:`; config `baseBranch`; the remote default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`, strip `origin/`; skip this when the command fails); `main`. Run `git fetch origin <base>`; failure: report and stop. From here the base is `BASE_REF=origin/<base>`, a ref for log and diff ranges only, never a branch to check out or push to. Pass it in the `BASE_BRANCH=` line of every prompt.
3. **Slug.** Lowercase the title, replace every run of characters outside `[a-z0-9]` with `-`, trim leading and trailing `-`, cut to 40 characters, trim a trailing `-` again. Empty result: `work`. Branch `<KEY>/<slug>`.
4. **Ignore pipeline paths.** The per-repo exclude file is `"$(git -C <root> rev-parse --path-format=absolute --git-common-dir)/info/exclude"`. Make sure it contains the lines `<ticketsDir>/*/state.json` and `/.claude/worktrees/`; append each one that is missing. (It is shared by all worktrees of the repository and is never committed.)
5. **Worktree.** Path `<root>/.claude/worktrees/<key-lower>-<slug>`. Take the first case that applies:
   1. *Adoption.* `<session-root>` is a linked worktree when `git -C <session-root> rev-parse --path-format=absolute --git-dir` differs from `--git-common-dir` (a launcher or Orca opened this session in its own worktree). Do not create anything and do not ask Reuse:
      - its branch matches `<KEY>/*`: adopt it;
      - its branch is clean and unused: `git status --porcelain` prints nothing (apart from this ticket's own `ticket.md`), `git rev-parse @{u}` fails, no `<ticketsDir>/*/state.json` exists in it, the branch is not another key's `<OTHER>/*`, and `git merge-base --is-ancestor HEAD BASE_REF` succeeds. Run `git branch -m <KEY>/<slug>` (stop if that branch already exists locally or on `origin`), then `git merge --ff-only BASE_REF`, and adopt it;
      - anything else: stop with a message naming the worktree and its branch. Create nothing.

      An adopted worktree is `<wt>` from here on; the path above does not apply.
   2. *Branch already exists* (locally or on `origin`): ask Reuse (recommended) · Abort. Reuse: `git worktree add <path> <branch>` on every host.
   3. *Host `orca`*: `orca worktree create --name <key-lower>-<slug> --branch <KEY>/<slug> --base-branch BASE_REF --setup skip --json`; take the path from its JSON (`result.worktree.path`, else `result.path`). If `orca` is missing or fails, report it and stop (do not fall back: a later retry would create a second worktree).
   4. *Otherwise* (`iterm`, `plain`): `git worktree add --no-track -b <branch> <path> BASE_REF` (`--no-track`, so a plain push never targets the base).
6. **Ticket dir and state.** `mkdir -p <wt>/<ticketsDir>/<KEY>`. If `<wt>/<ticketsDir>/<KEY>/ticket.md` does not exist (the base branch does not carry it), copy the file from step 1 there. Check `git -C <wt> check-ignore -q <ticketsDir>/<KEY>/state.json`; if it fails, stop and report it (the worktree stays; no `state.json` is written into a tree that would track it). Write `state.json`: `ticket`, `title`, `baseBranch` (bare name), `baseRef`, `branch`, `worktree` (absolute), `host`, `stage: "spec"`, `reviewRound: 0`, `decisions: []`, `warnings: []`, `prUrl: null`, `updatedAt`. Create `decisions.md` with the heading `# Decisions`.
7. **Setup.** If `setupCommand` is set, run it with `cd <wt> &&`. Failure is an infrastructure blocker: H6 (Retry · Skip · Abort, section 7). Skip is recorded in `state.warnings` and `decisions.md`; Abort sets `abortedFrom: "spec"` and `stage: "aborted"` (section 10).
8. **Session name.** When `TICKET_FLOW_KEY` is unset (a session started by hand), print one line suggesting `/rename <KEY> · <short title>`. The short title is the title with every character outside `[A-Za-z0-9 .,:()/_-]` replaced by a space, spaces collapsed, cut at the last word boundary within 40 characters. You cannot rename a session yourself.
9. Continue with the spec stage.

## 4. Stage prompt and result handling

### Prompt

Build every stage prompt with exactly these lines, in the contract the agents define:

```
WORKTREE=<abs worktree path>
KEY=<KEY>
TICKET_DIR=<abs worktree path>/<ticketsDir>/<KEY>
BASE_BRANCH=<BASE_REF, e.g. origin/main>
MODE=implement|fix-review          (ticket-dev only)
REVIEW_ROUND=<n>                   (ticket-dev with MODE=fix-review only)
FORMAT_CMD=<formatCommand>         (ticket-dev only, when configured)
DECISIONS:
<YAML list of state.decisions: stage, question, answer, at; "[]" when empty>
PROJECT_RULES:                     (only when escalationExtra is not empty)
<one "- <rule>" line per entry of escalationExtra>
```

`REVIEW_ROUND` is `reviewRound` after it was incremented (section 8). For the planner, append the developer's change request under a `FEEDBACK:` line when re-planning. Spawn with the Agent tool: `subagent_type` from the table above, a short `description`, and `model` from `models` (`spec`, `plan`, `dev`; for the reviewer see section 8). Foreground only. Do not pass `effort`; the agent files carry it.

### Parse

Read the agent's final message in this order:

1. **`NEEDS_DECISION`** as a line of its own anywhere (even with a `RESULT:` line): parse `stage`, `question`, `context`, `options` (`label | consequence`), `recommendation`. Ask H1 (`stage: spec`) or H3 (any other stage) with the options plus free text, recommended first. Append the answer to `decisions.md` (a `## <ISO time> (<stage>)` entry with question and answer) and to `state.decisions` (with `at`), then run **the same stage again**. Once the plan is approved (stage `dev` or later) `decisions.md` is tracked: after each append, format it and commit it alone with an explicit pathspec (`git -C <wt> commit -m "docs(<KEY>): record decisions" -m "<trailer>" -- <path>`). Before H2 it stays uncommitted. A denied or gated call reported this way is handled the same: show the exact command and reason; if the developer says go ahead, record that as the decision and re-run the stage.
2. **`RESULT: OK <path>`** as the last non-empty line: the file must exist at that path; otherwise it is a failed run.
3. **Anything else** (empty, tool error, crash, no marker): failed run. Retry the same stage **once** automatically. A second failure goes to H7 (Retry · Abort) with an error summary.

### Scope check

After spec, plan and review stages only `<ticketsDir>/<KEY>/` may change. Run `git -C <wt> status --porcelain`. Any path outside that directory fails the stage: discard nothing, list the paths, and go to H7 (Retry · Abort) without the automatic retry.

## 5. Spec stage

Stage `spec`. Spawn the spec agent. On `RESULT: OK`, run the scope check. A blocking question arrives as `NEEDS_DECISION` with `stage: spec` (H1): handle it per section 4 and re-run. Then set `stage: "plan"`.

## 6. Plan stage and the plan gate (H2)

Stage `plan`. Spawn the planner. A `NEEDS_DECISION` is handled per section 4 and the planner re-runs. On `RESULT: OK`, run the scope check, set `stage: "awaiting_plan_approval"`, then ask **H2**. Show:

- a short summary of the plan (steps in order, verification choice);
- the path to `plan.md`;
- the whole `## Gated operations` table (or "None");
- open decisions or risks the plan flags.

Options: **Approve (recommended)** · **Request changes** · **Abort**.

- **Request changes:** take the free text, set `stage: "plan"`, re-run the planner with it under `FEEDBACK:`, then ask H2 again. No round limit.
- **Abort:** section 10.
- **Approve:**
  1. `git -C <wt> status --porcelain`: a path outside `<ticketsDir>/<KEY>/` is a scope failure (section 4); never approve with stray changes.
  2. Format `ticket.md`, `spec.md`, `plan.md`, `decisions.md`, then `git -C <wt> add` those four files only.
  3. Commit with the subject `docs(<KEY>): add spec and plan` and the trailer.
  4. Set `stage: "dev"`.

Approving the plan also authorises the rest of the run's normal actions: local commits, pushing the ticket branch and opening the PR. Do not ask about them again. Never force push or push to any branch other than the ticket branch.

## 7. Dev stage and blockers (H6)

Stage `dev`. Spawn the dev agent with `MODE=implement`. On `RESULT: OK`, `dev-report.md` exists; check that `git -C <wt> log --format=%H --grep='^Plan-Step: ' <BASE_REF>..HEAD` prints at least one commit (none: failed run) and that `git -C <wt> status --porcelain` is clean. Leftover changes: show them and ask **Commit them (recommended)** (format, stage with the exclude pathspec above, commit `chore(<KEY>): commit leftover changes from dev stage` plus the trailer) · **Stash** (`git stash push -u`) · **Abort**. Then set `stage: "review"`.

**H6.** A dev `NEEDS_DECISION` whose `question:` starts with `verification failed:` (the agent's 2 fix attempts are used up; every other dev `NEEDS_DECISION` is H3), and any infrastructure blocker (setup fails, Docker down, a service will not start), get the same prompt: the failing command and an output excerpt, options **Retry** · **Skip this check** · **Abort**.

- Retry: re-run the stage (dev) or the command.
- Skip: append `{stage, command, reason, at}` to `state.warnings` and record the skip as a decision (section 4); it is listed under "Skipped checks" in the PR. If the skip answers a dev `NEEDS_DECISION`, there is no `dev-report.md`: do not re-run dev; write a minimal one yourself (`## Steps done` from the `Plan-Step:` commits, `## Verification` with the skipped command marked SKIPPED and its reason, `## Deviations from the plan`: "None known; verification skipped for the reason above"), format and commit it as `docs(<KEY>): add dev report` plus the trailer, then continue to review.
- Abort: section 10. Never launch or restart apps or Docker to clear a blocker.

## 8. Review stage and loop

Stage `review`. Choose the reviewer model: run `git -C <wt> diff --name-only <BASE_REF>...HEAD -- <pathspecs>` with one `':(glob)<pattern>'` per entry of `riskPaths`. Default `riskPaths`: `**/migrations/**`, `**/*policy*`, `**/auth/**`, `**/*.tf`, `infra/**`, `.github/workflows/**`, `.claude/**`. Any output: `models.reviewRisk`; none: `models.review`.

Spawn the reviewer. On `RESULT: OK`, `review.md` must exist and its last line must be `VERDICT: PASS` or `VERDICT: CHANGES_REQUIRED`; otherwise it is a failed run. Run the scope check, then format and commit `review.md` as `docs(<KEY>): add review round <reviewRound+1>` plus the trailer.

- `VERDICT: PASS`: set `stage: "complete"` and go to section 9a.
- `VERDICT: CHANGES_REQUIRED`:
  - `reviewRound >= 2`: ask **H5** with the remaining findings: **Accept as is** (go to 9a; append `{stage: "review", command: "accepted open findings", reason: <findings>, at}` to `state.warnings`) · **One more round** (continue below) · **Take over manually** (leave `stage: "review"`, print the worktree path and how to resume, stop).
  - Otherwise increment `reviewRound`, run the dev agent with `MODE=fix-review` and `REVIEW_ROUND=<reviewRound>`, handle its result as in section 7 (a fix round adds `Review-Fix:` commits, so skip the `Plan-Step:` check), then review again.

Minor findings are never auto-fixed; they are listed in the PR.

## 9. Resume

`--resume` (and Resume from section 1) re-enters the recorded `stage` from its start. First:

1. Read the config again (section 0) and repeat the exclude and `check-ignore` checks of section 3, steps 4 and 6 (the exclude entries may be missing in a fresh clone).
2. `git -C <wt> status --porcelain`. In stages `spec`, `plan` and `awaiting_plan_approval`, changes inside `<ticketsDir>/<KEY>/` are the stage's own output; in stage `review` the same holds for `review.md`. Any other change must be shown before you spawn anything: in stages `dev` and `complete` ask **Keep and continue (recommended)** · **Stash** · **Abort**; in every other stage ask **Stash (recommended)** · **Abort**.
3. Stage `awaiting_plan_approval`: ask H2 again. Stage `aborted`: ask which stage to re-enter (default `abortedFrom`). Stage `done`: report the PR and stop.
4. Stage `dev`: re-run the agent (it skips steps whose `Plan-Step: N` trailer is already in the log). Stage `review`: re-run the reviewer. Stage `complete`: section 9a (it reuses an existing PR).

## 9a. Complete

Stage `complete`. You do this yourself; no subagent.

1. Run the `## Verification` commands of `plan.md` in order, one at a time with `cd <wt> &&`, minus checks skipped under H6. Failure, or a needed app or service that is down: H6. Never start them.
2. The tree must be clean (leftovers: the Commit · Stash · Abort question of section 7). Push: `git -C <wt> push -u origin <branch>`. Plain push of the ticket's own branch only; never force.
3. Write the PR body to a file in the scratchpad (not in the worktree), with these sections in order:
   - `## Summary`: what changed and why, from `spec.md` and `dev-report.md`.
   - `## Spec & plan`: links to `<ticketsDir>/<KEY>/ticket.md`, `spec.md` and `plan.md` on the branch.
   - `## Verification`: each command and its result.
   - `## Open minor findings`: the `## Minor` list of `review.md`, plus findings accepted under H5 (or "None").
   - `## Skipped checks`: every `state.warnings` entry with its `command` and `reason` (or "None").

   End the body with the pull-request attribution line your session's instructions specify, if any.
4. Open the PR: if `gh pr list --head <branch> --json url` returns one, reuse it; otherwise `gh pr create --base <baseBranch> --head <branch> --title "<type>(<KEY>): <title>" --body-file <file>`. The type comes from the spec (`feat` by default, `fix` for bugs, `docs` for documentation-only work). Save the URL as `prUrl`.
5. Set `stage: "done"` and print the final report: PR URL, worktree path, the decisions taken, the warnings, the minor findings still open. The worktree and branch are kept; remove them after the merge (`git worktree remove <wt>`, or `orca worktree rm --worktree path:<wt>` when the host is `orca`).

## 10. Abort

On Abort (H2, H6, H7, a restart, or a user request): set `abortedFrom` to the current stage, `stage: "aborted"`, and **keep** the worktree and branch untouched. Tell the developer the worktree path and that `/ticket <KEY> --resume` continues.
