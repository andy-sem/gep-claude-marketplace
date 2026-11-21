---
name: ticket
description: Run a ticket file through the spec, plan, dev, review and PR pipeline with one subagent per stage, in its own git worktree. Use when the user invokes /ticket <KEY> (optionally with --resume, --status or --address-review), or says "start working on ticket <KEY>", "pick up <KEY>", "resume <KEY>", "status of <KEY>", "address review on <KEY>" or "fix PR comments on <KEY>". The ticket is a Markdown file (docs/tickets/<KEY>/ticket.md by default) or a description the user pastes.
---

# /ticket: ticket pipeline orchestrator

You are the orchestrator. You run in the main session, never write product code yourself, and drive four stage subagents through one ticket:

| Stage | Agent (`subagent_type`) | Writes |
| --- | --- | --- |
| spec | `gated-dev-simple-workflow:ticket-spec` | `spec.md` |
| plan | `gated-dev-simple-workflow:ticket-planner` | `plan.md` |
| dev | `gated-dev-simple-workflow:ticket-dev` | commits, `dev-report.md` |
| review | `gated-dev-simple-workflow:ticket-reviewer` | `review.md` |

The pipeline is file-based: the ticket is `ticket.md`, and every stage reads and writes files in the ticket directory. The pipeline itself knows no issue tracker; a project can connect one through `orchestratorRules` (section 0a). The design (interaction points H1 to H7, the `NEEDS_DECISION` protocol, stages, state file) is in `references/pipeline-spec.md`; the per-project settings are in `references/config.md`. Read the section you are acting on instead of working from memory.

Rules that hold everywhere:

- Every stop for the developer goes through `AskUserQuestion`, recommended option first (the H-points). Calls that an approval gate stops use the normal permission prompt (H4); you do not handle those.
- Spawn every stage subagent in the **foreground** (never `run_in_background`) and pass `model` explicitly (section 4). The only background work is the PR watcher of section 9c: a Bash command with `run_in_background: true`, not a subagent.
- Never launch, restart or stop apps, dev servers or Docker. If something needs them and they are down, that is an infrastructure blocker (H6).
- Never route around an approval gate, and never run a gated operation that the approved plan does not list. Do not edit product files yourself.
- Keep `state.json` current: after every transition set the new `stage` and `updatedAt` (ISO-8601). Re-read it before every write, write the whole file and keep its `watch` field as it is: only the watcher of section 9c writes `watch`.
- `state.json` is never committed. Never stage it, and never run a bare `git add -A`: when staging everything, use `git -C <wt> add -A -- . ':(exclude)<ticketsDir>/*/state.json'`.
- Commit trailer: end every commit message you write with the `Co-Authored-By` attribution line that your session's instructions specify for commits. Do not hard-code a model name; if the session specifies no attribution, add none. "The trailer" below means this line.
- Scripts and hooks of this plugin live under `${CLAUDE_PLUGIN_ROOT}` (`scripts/watch_pr.py`, `hooks/notify.py`). The scripts need Python >= 3.14: start them with `python3 -I`, or with `"$GATE_INFRA_PYTHON" -I` when `python3` is older and that variable is set.
- Formatting: "format `<files>`" below means: run `<formatCommand> <files>` in the worktree when `formatCommand` is configured; otherwise do nothing.
- Project rules: "**Event `<name>`**" below means: when `orchestratorRules` is configured and its file has a `## <name>` section, do what that section says now, then continue (see section 0a). Without the key or the section, nothing happens.

## 0. Configuration and host

1. `<session-root>` is the top level of the checkout this session started in (`$CLAUDE_PROJECT_DIR`, else `git rev-parse --show-toplevel`). `<root>` is the main checkout: the first `worktree` entry of `git worktree list --porcelain`.
2. Read `<session-root>/.claude/gated-dev.json` if it exists (all keys optional; see `references/config.md`). Invalid JSON or an unknown key: report it and stop; never guess. Defaults: `ticketsDir` `docs/tickets`, `keyPattern` `^[A-Za-z][A-Za-z0-9._-]*$`, `baseBranch` unset, `setupCommand` unset, `formatCommand` unset, `riskPaths` (section 8), `escalationExtra` `[]`, `models` `{spec: sonnet, plan: opus, dev: sonnet, review: sonnet, reviewRisk: opus}`, `orchestratorRules` unset. When `orchestratorRules` is set, read that file (`<session-root>/<orchestratorRules>`) now; a missing file, or a `## ` heading that is not an event name of section 0a, is a config error: report it and stop.
3. Gate dry-run. When the skill `destructive-guard:check` is in your list of available skills (the gate plugin is installed and enabled), find its script: in `~/.claude/plugins/installed_plugins.json`, take the `installPath` of the `destructive-guard@<marketplace>` entry whose `projectPath` is `<root>` (scope `project` or `local`), else the one with scope `user`, and check which script exists: `<installPath>/lib/check.py` (current gate; run it with `python3 -I`, or with `$GATE_INFRA_PYTHON` when that is set) or, for an older installed gate, `<installPath>/lib/check.mjs` (run it with `node`). Then `GATE_CHECK=CLAUDE_PROJECT_DIR='<session-root>' python3 -I '<installPath>/lib/check.py' --json --cwd '<wt>'` (or the `node` form for `check.mjs`) (set `<wt>` once the worktree exists; `CLAUDE_PROJECT_DIR` makes the dry-run read relative gate paths from the same checkout as the session's gate hook). Neither script found, or `python3` older than 3.14 with no `GATE_INFRA_PYTHON`: no `GATE_CHECK` (the planner then writes `unknown` rule IDs). Never pass `--jev`.
4. Host: `orca` when `TERM_PROGRAM=Orca`, or `ORCA_TERMINAL_HANDLE` is set and `TERM_PROGRAM` is not `iTerm.app`; `iterm` when `TERM_PROGRAM=iTerm.app` or `ITERM_SESSION_ID` is set; otherwise `plain`. An `orca` host also needs the repo registered in Orca: if `orca repo show --repo path:<root> --json` fails (or `orca` is not on `PATH`), the host is `plain` and you say so in one line ("<root> is not an Orca repo; using git worktrees"). Only `orca` changes how worktrees are created and removed; `iterm` and `plain` use git directly.

## 0a. Project rules (`orchestratorRules`)

A project can add its own steps to the pipeline, for example to keep an issue tracker in step, without changing it. The file is Markdown: one `## <event>` section per event below, in any order, each saying what to do in plain words; text before the first `## ` heading is shared context for every section (ids, URLs, conventions). The section for an event runs at the point marked **Event `<name>`** in this skill.

| Event | When |
| --- | --- |
| `intake` | Kickoff, step 1: no `ticket.md` and no pasted description. The section may write `ticket.md` (with front matter `base:` if it decides the base). |
| `started` | Kickoff done: worktree, `state.json` and setup exist. |
| `resumed` | `--resume`, after the checks of section 9 step 1. |
| `spec-done` | Spec stage finished. |
| `plan-approved` | H2 approved and the spec and plan committed. |
| `dev-done` | Dev stage finished (also after each fix round). |
| `review-done` | Each review verdict (`VERDICT` and `reviewRound` are known). |
| `pr-body` | Writing the PR body (section 9a step 3). The section may give lines to add under `## Spec & plan`. |
| `pr-opened` | The PR exists (`prUrl` is set). |
| `pr-feedback-addressed` | A PR feedback round of section 9b is closed. |
| `merged` | Section 9d, after the final report and before the notification and worktree removal. |
| `aborted` | Section 10, with the reason. |

Rules for following them:

- You do the actions yourself with the tools the session has; stage subagents never see the file. Every call still goes through the approval gate and the normal permission rules. The developer wrote the file, so its actions need no extra confirmation unless the section asks for one.
- The rules add steps; they never change the pipeline. Ignore anything in the file that would skip or answer an H-point, write product code, change what a stage agent gets, run a gated operation the plan does not list, push anything other than the ticket branch, or remove a worktree or branch.
- Values you can use: `KEY`, the title, `TICKET_DIR`, branch, worktree, base branch, stage, `reviewRound`, the verdict, `prUrl`, the abort reason, and the files in `TICKET_DIR`. To keep a value between events (for example an id looked up at `started`), store it under `state.rules` (an object; keep it on every write of `state.json`).
- A failing action never stops the run, except at `intake` (then kickoff stops as step 1 says): append `{stage: "rules", command: "<event>: <action>", reason, at}` to `state.warnings` and continue. Retry only when the file says so. `--status` shows these warnings; the PR does not list them under "Skipped checks".

## 1. Arguments

1. Take the key from the user's text. It must match `keyPattern` and must not contain `/` or `..`; otherwise ask for it and stop.
2. Flags: `--resume` ("resume <KEY>"), `--status` ("status of <KEY>"), `--address-review` ("address review on <KEY>", "fix PR comments on <KEY>"). At most one; if several are given, ask which. No flag means a new run ("start working on", "pick up").
3. Find an existing run: in `git worktree list --porcelain`, look for a worktree whose branch matches `refs/heads/<KEY>/*`. Its state file is `<wt>/<ticketsDir>/<KEY>/state.json`. If several match, keep the one whose `stage` is not `aborted`; if that still leaves zero or more than one, ask which to use. Set `TICKET_DIR=<wt>/<ticketsDir>/<KEY>`.
4. Cases:
   - `--status`: no worktree or no state file: report "no state found for <KEY>", change nothing, stop. Otherwise section 2.
   - `--resume`: no worktree or no state file: say there is nothing to resume and offer a new run. Otherwise section 9 (stage `done` restarts the PR watch of section 9c, stage `merged` re-runs section 9d).
   - `--address-review`: no worktree or no state file: report "no state found for <KEY>", change nothing, stop. Otherwise section 9b.
   - No flag, state exists: ask Resume (recommended) · Restart. Restart asks once more for confirmation, sets the old run to `aborted` (section 10), and runs kickoff with a fresh slug suffix (`-2`, `-3`, ...) so the branch differs. Never delete a worktree or branch.
   - No flag, no state: kickoff (section 3). A worktree found in step 3 without a state file (opened by a launcher or by Orca, no run started yet) is adopted by kickoff, not duplicated (section 3, step 5.1).

## 2. Status (read-only)

Read `state.json` and print: ticket, title, stage (and `reviewRound`), branch, worktree, base branch, PR URL if any, `lastAddressedCommentAt` if set (stage `addressing_review` means PR feedback is being addressed), `watch.heartbeatAt` if set (the PR watcher of section 9c is alive while it is less than 3 minutes old), the number of recorded decisions with the last question, every entry of `warnings`, and the paths of `ticket.md`, `spec.md`, `plan.md`, `decisions.md`, `dev-report.md`, `review.md` and `pr-feedback-<n>.md` that exist. "Open questions" means: stage `awaiting_plan_approval` (the plan waits for approval), or the unresolved `## Open questions` of `spec.md` when the stage is `spec`. Write nothing, spawn nothing.

## 3. Kickoff

Steps 1 to 5 stop with a clear message on any failure and leave nothing behind. Once the worktree exists, a failure never removes it: keep the worktree and branch, follow H6 or the abort rules, and record what happened in `state.json`.

1. **Ticket file.** Look for `<session-root>/<ticketsDir>/<KEY>/ticket.md`.
   - It exists: use it. If the user also pasted a description, ask Use the file (recommended) · Replace it with the pasted text.
   - It does not exist and the user's message carries a description (anything beyond the key and flags): this text is the ticket. Write it to that path, with a `# <title>` first line (the user's title, or a short one you derive) followed by the text verbatim.
   - Neither: **Event `intake`**. If the file exists afterwards, use it. Otherwise tell the user to create `<ticketsDir>/<KEY>/ticket.md` or to paste a description with the command, and stop.

   An empty file, or one with no `# ` heading, is not a ticket: say so and stop. Read the optional YAML front matter (`---` block at the top): `base:` (a branch name) is the only key the orchestrator uses. The title is the first `# ` heading.
2. **Base branch.** The first that applies: front matter `base:`; config `baseBranch`; the remote default branch (`git symbolic-ref --short refs/remotes/origin/HEAD`, strip `origin/`; skip this when the command fails); `main`. Run `git fetch origin <base>`; failure: report and stop. From here the base is `BASE_REF=origin/<base>`, a ref for log and diff ranges only, never a branch to check out or push to. Pass it in the `BASE_BRANCH=` line of every prompt.
3. **Slug.** Lowercase the title, replace every run of characters outside `[a-z0-9]` with `-`, trim leading and trailing `-`, cut to 40 characters, trim a trailing `-` again. Empty result: `work`. Branch `<KEY>/<slug>`.
4. **Ignore pipeline paths.** The per-repo exclude file is `"$(git -C <root> rev-parse --path-format=absolute --git-common-dir)/info/exclude"`. Make sure it contains the lines `<ticketsDir>/*/state.json` and `/.claude/worktrees/`; append each one that is missing. (It is shared by all worktrees of the repository and is never committed.)
5. **Worktree.** Path `<root>/.claude/worktrees/<key-lower>-<slug>`. Take the first case that applies:
   1. *Adoption.* Adopt the worktree found in section 1 step 3 (its branch matches `<KEY>/*`, so it is this ticket's), wherever it lives and whichever checkout this session started in. Otherwise `<session-root>` is a linked worktree when `git -C <session-root> rev-parse --path-format=absolute --git-dir` differs from `--git-common-dir` (a launcher or Orca opened this session in its own worktree). Do not create anything and do not ask Reuse:
      - its branch matches `<KEY>/*`: adopt it;
      - its branch is clean and unused: `git status --porcelain` prints nothing (apart from this ticket's own `ticket.md`), `git rev-parse @{u}` fails, no `<ticketsDir>/*/state.json` exists in it, the branch is not another key's `<OTHER>/*`, and `git merge-base --is-ancestor HEAD BASE_REF` succeeds. Run `git branch -m <KEY>/<slug>` (stop if that branch already exists locally or on `origin`), then `git merge --ff-only BASE_REF`, and adopt it;
      - anything else: stop with a message naming the worktree and its branch. Create nothing.

      An adopted worktree is `<wt>` from here on; the path above does not apply.
   2. *Branch already exists* (locally or on `origin`): ask Reuse (recommended) · Abort. Reuse: if `git worktree list --porcelain` shows the branch checked out in some worktree, adopt that worktree; otherwise `git worktree add <path> <branch>` on every host.
   3. *Host `orca`*: `orca worktree create --repo path:<root> --name <key-lower>-<slug> --branch <KEY>/<slug> --base-branch BASE_REF --setup skip --json`; take the path from its JSON (`result.worktree.path`, else `result.path`). If it fails, report it and stop (do not fall back: a later retry would create a second worktree).
   4. *Otherwise* (`iterm`, `plain`): `git worktree add --no-track -b <branch> <path> BASE_REF` (`--no-track`, so a plain push never targets the base).
6. **Ticket dir and state.** `mkdir -p <wt>/<ticketsDir>/<KEY>`. If `<wt>/<ticketsDir>/<KEY>/ticket.md` does not exist (the base branch does not carry it), copy the file from step 1 there. Check `git -C <wt> check-ignore -q <ticketsDir>/<KEY>/state.json`; if it fails, stop and report it (the worktree stays; no `state.json` is written into a tree that would track it). Write `state.json`: `ticket`, `title`, `baseBranch` (bare name), `baseRef`, `branch`, `worktree` (absolute), `host`, `stage: "spec"`, `reviewRound: 0`, `decisions: []`, `warnings: []`, `prUrl: null`, `updatedAt`. Create `decisions.md` with the heading `# Decisions`.
7. **Setup.** If `setupCommand` is set, run it with `cd <wt> &&`. Failure is an infrastructure blocker: H6 (Retry · Skip · Abort, section 7). Skip is recorded in `state.warnings` and `decisions.md`; Abort sets `abortedFrom: "spec"` and `stage: "aborted"` (section 10).
8. **Session name.** When `TICKET_FLOW_KEY` is unset (a session started by hand), print one line suggesting `/rename <KEY> · <short title>`. The short title is the title with every character outside `[A-Za-z0-9 .,:()/_-]` replaced by a space, spaces collapsed, cut at the last word boundary within 40 characters. You cannot rename a session yourself.
9. **Event `started`**.
10. Continue with the spec stage.

## 4. Stage prompt and result handling

### Prompt

Build every stage prompt with exactly these lines, in the contract the agents define:

```
WORKTREE=<abs worktree path>
KEY=<KEY>
TICKET_DIR=<abs worktree path>/<ticketsDir>/<KEY>
BASE_BRANCH=<BASE_REF, e.g. origin/main>
MODE=implement|fix-review|fix-pr   (ticket-dev only)
REVIEW_ROUND=<n>                   (ticket-dev with MODE=fix-review only)
FEEDBACK=<abs path>                (ticket-dev with MODE=fix-pr only, section 9b)
REVIEW_SINCE=<commit>              (ticket-reviewer in section 9b only)
FORMAT_CMD=<formatCommand>         (ticket-dev only, when configured)
GATE_CHECK=<command>               (ticket-planner only, when found in section 0)
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

Stage `spec`. Spawn the spec agent. On `RESULT: OK`, run the scope check. A blocking question arrives as `NEEDS_DECISION` with `stage: spec` (H1): handle it per section 4 and re-run. Then set `stage: "plan"`. **Event `spec-done`**.

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
  4. Set `stage: "dev"`. **Event `plan-approved`**.

Approving the plan also authorises the rest of the run's normal actions: local commits, pushing the ticket branch and opening the PR. Do not ask about them again. Never force push or push to any branch other than the ticket branch.

## 7. Dev stage and blockers (H6)

Stage `dev`. Spawn the dev agent with `MODE=implement`. On `RESULT: OK`, `dev-report.md` exists; check that `git -C <wt> log --format=%H --grep='^Plan-Step: ' <BASE_REF>..HEAD` prints at least one commit (none: failed run) and that `git -C <wt> status --porcelain` is clean. Leftover changes: show them and ask **Commit them (recommended)** (format, stage with the exclude pathspec above, commit `chore(<KEY>): commit leftover changes from dev stage` plus the trailer) · **Stash** (`git stash push -u`) · **Abort**. Then set `stage: "review"`. **Event `dev-done`**.

**H6.** A dev `NEEDS_DECISION` whose `question:` starts with `verification failed:` (the agent's 2 fix attempts are used up; every other dev `NEEDS_DECISION` is H3), and any infrastructure blocker (setup fails, Docker down, a service will not start), get the same prompt: the failing command and an output excerpt, options **Retry** · **Skip this check** · **Abort**.

- Retry: re-run the stage (dev) or the command.
- Skip: append `{stage, command, reason, at}` to `state.warnings` and record the skip as a decision (section 4); it is listed under "Skipped checks" in the PR. If the skip answers a dev `NEEDS_DECISION`, there is no `dev-report.md`: do not re-run dev; write a minimal one yourself (`## Steps done` from the `Plan-Step:` commits, `## Verification` with the skipped command marked SKIPPED and its reason, `## Deviations from the plan`: "None known; verification skipped for the reason above"), format and commit it as `docs(<KEY>): add dev report` plus the trailer, then continue to review.
- Abort: section 10. Never launch or restart apps or Docker to clear a blocker.

## 8. Review stage and loop

Stage `review`. Choose the reviewer model: run `git -C <wt> diff --name-only <BASE_REF>...HEAD -- <pathspecs>` with one `':(glob)<pattern>'` per entry of `riskPaths`. Default `riskPaths`: `**/migrations/**`, `**/*policy*`, `**/auth/**`, `**/*.tf`, `infra/**`, `.github/workflows/**`, `.claude/**`. Any output: `models.reviewRisk`; none: `models.review`.

Spawn the reviewer. On `RESULT: OK`, `review.md` must exist and its last line must be `VERDICT: PASS` or `VERDICT: CHANGES_REQUIRED`; otherwise it is a failed run. Run the scope check, then format and commit `review.md` as `docs(<KEY>): add review round <reviewRound+1>` plus the trailer. **Event `review-done`**.

- `VERDICT: PASS`: set `stage: "complete"` and go to section 9a.
- `VERDICT: CHANGES_REQUIRED`:
  - `reviewRound >= 2`: ask **H5** with the remaining findings: **Accept as is** (go to 9a; append `{stage: "review", command: "accepted open findings", reason: <findings>, at}` to `state.warnings`) · **One more round** (continue below) · **Take over manually** (leave `stage: "review"`, print the worktree path and how to resume, stop).
  - Otherwise increment `reviewRound`, run the dev agent with `MODE=fix-review` and `REVIEW_ROUND=<reviewRound>`, handle its result as in section 7 (a fix round adds `Review-Fix:` commits, so skip the `Plan-Step:` check), then review again.

Minor findings are never auto-fixed; they are listed in the PR.

## 9. Resume

`--resume` (and Resume from section 1) re-enters the recorded `stage` from its start. First:

1. Read the config again (section 0) and repeat the exclude and `check-ignore` checks of section 3, steps 4 and 6 (the exclude entries may be missing in a fresh clone). Then **Event `resumed`**.
2. `git -C <wt> status --porcelain`. In stages `spec`, `plan` and `awaiting_plan_approval`, changes inside `<ticketsDir>/<KEY>/` are the stage's own output; in stage `review` the same holds for `review.md`. Any other change must be shown before you spawn anything: Stage `merged` needs no question (section 9d keeps a dirty worktree). In stages `dev`, `complete`, `done` and `addressing_review` ask **Keep and continue (recommended)** · **Stash** · **Abort**; in every other stage ask **Stash (recommended)** · **Abort**.
3. Stage `awaiting_plan_approval`: ask H2 again. Stage `aborted`: ask which stage to re-enter (default `abortedFrom`). Stage `addressing_review`: section 9b from step 1 (its PR-state check sends a merged PR to section 9d and stops on a closed one; for an open PR it continues at step 3, the tree check was done here). Stage `done`: report the PR and go to section 9c (the watch restarts). Stage `merged`: section 9d.
4. Stage `dev`: re-run the agent (it skips steps whose `Plan-Step: N` trailer is already in the log). Stage `review`: re-run the reviewer. Stage `complete`: section 9a (it reuses an existing PR).

## 9a. Complete

Stage `complete`. You do this yourself; no subagent.

1. Run the `## Verification` commands of `plan.md` in order, one at a time with `cd <wt> &&`, minus checks skipped under H6. Failure, or a needed app or service that is down: H6. Never start them.
2. The tree must be clean (leftovers: the Commit · Stash · Abort question of section 7). Push: `git -C <wt> push -u origin <branch>`. Plain push of the ticket's own branch only; never force.
3. Write the PR body to a file in the scratchpad (not in the worktree), with these sections in order:
   - `## Summary`: what changed and why, from `spec.md` and `dev-report.md`.
   - `## Spec & plan`: links to `<ticketsDir>/<KEY>/ticket.md`, `spec.md` and `plan.md` on the branch, plus any lines from **Event `pr-body`**.
   - `## Verification`: each command and its result.
   - `## Open minor findings`: the `## Minor` list of `review.md`, plus findings accepted under H5 (or "None").
   - `## Skipped checks`: every `state.warnings` entry with its `command` and `reason` (or "None").

   End the body with the pull-request attribution line your session's instructions specify, if any.
4. Open the PR: if `gh pr list --head <branch> --json url` returns one, reuse it; otherwise `gh pr create --base <baseBranch> --head <branch> --title "<type>(<KEY>): <title>" --body-file <file>`. The type comes from the spec (`feat` by default, `fix` for bugs, `docs` for documentation-only work). Save the URL as `prUrl`. **Event `pr-opened`** (also when an existing PR was reused).
5. Set `stage: "done"` and print the final report: PR URL, worktree path, the decisions taken, the warnings, the minor findings still open. Then go to section 9c.

## 9b. Address PR review (`--address-review`)

Stage `addressing_review`. Runs when the PR of a finished run has new human feedback: started by the developer with `--address-review`, or by the watch of section 9c. The only subagents are `ticket-dev` (`MODE=fix-pr`, then `fix-review` if needed) and `ticket-reviewer`. This section authorises the commits, the plain push of the ticket branch and the GitHub replies below, and nothing else. Never force push, resolve a review thread or re-request a review. Every PR reply starts with the marker line `<!-- gated-dev -->`; the watcher ignores comments that carry it.

1. **Preconditions.** `stage` must be `done` or `addressing_review`, and `prUrl` must be set with `gh pr view <prUrl> --json state,number,createdAt,headRefName` reporting `OPEN`. `MERGED`: section 9d. `CLOSED`: report it and stop. Any other stage or state: report it and stop. Whenever it stops here it changes nothing except `updatedAt`. Unless you arrive from section 9 (which did both), run the working-tree check of section 9, step 2 (stage `done` counts like `complete`) and the exclude and `check-ignore` checks of section 3, steps 4 and 6.
2. **Stage.** Set `stage: "addressing_review"`.
3. **Collect feedback.** Read reviews and issue comments with `gh pr view <prUrl> --json reviews,comments` and inline comments with `gh api repos/{owner}/{repo}/pulls/{n}/comments --paginate`, keeping `id`, `path`, `line`, `in_reply_to_id`, `created_at`, `user.login` and `body`. A review's time is its `submittedAt`. Keep an item only if it is newer than `lastAddressedCommentAt` (the PR's `createdAt` when that is absent), its author is not a bot (login ends in `[bot]`), and its body is not empty and does not contain the marker; a review with an empty body counts only when its state is `CHANGES_REQUESTED`. For a reply inside a thread, also keep the thread's root comment as context.
   - If the highest-numbered `pr-feedback-<n>.md` has an item newer than `lastAddressedCommentAt`, that round was interrupted: reuse that file and number and go to step 4 (items already fixed or answered show up as `PR-Fix:` trailers and marked replies; steps 6 and 8 skip them). Otherwise `n` is the next free number.
   - Nothing kept: set `lastAddressedCommentAt` to the newest time among the items that passed the time filter (if any, so the watcher does not wake for them again), `stage: "done"`, report "no new PR feedback" and go to section 9c.
4. **Sync the branch.** `git -C <wt> fetch origin <branch>`, then `git -C <wt> merge --ff-only origin/<branch>` so the local branch is not behind. If the branches diverged, show the divergence and ask H6-style **Retry** · **Abort**; never rebase, merge or force push on your own.
5. **Classify.** Write `TICKET_DIR/pr-feedback-<n>.md`: a header with the PR URL, the collection time and `Base commit: <sha of HEAD now>`, then one `## Item <id>` block per item with `Source` (inline, review or comment), `Author`, `Created`, `Location` (`path:line` or n/a), `Thread` (root id or none), `Body`, `Class` and `Plan` (what to change, the draft answer, or the reason to decline). Decide `Class` yourself: `change` (actionable), `question` (needs an answer, no code), `decline` (you would not make the change). Answer `question` items from `spec.md`, `plan.md`, `dev-report.md` and the diff. Ask the developer (H3, recommended option first) before dev runs when an item is ambiguous, changes scope or acceptance criteria, falls under the escalation list of the pipeline (`references/pipeline-spec.md` §4, plus `escalationExtra`), needs a gated operation the plan does not list, is a `question` you cannot answer, or is a `decline` (always confirm: **Decline with reason (recommended)** · **Make the change** · **Skip without a reply**). Record the answers per section 4 (stage `addressing_review`), update `Class` and `Plan` to the outcome, then format the file and commit it alone as `docs(<KEY>): add PR feedback round <n>` plus the trailer. If no item is `change`, skip steps 6 and 7 and the verification and push of step 8, and only post the replies.
6. **Dev.** Spawn `ticket-dev` with `MODE=fix-pr` and `FEEDBACK=<abs path of pr-feedback-<n>.md>`. It fixes every `change` item, commits with `PR-Fix: <comment id>` trailers and appends `## PR feedback round <n>` to `dev-report.md`. Handle the result as in section 7: `NEEDS_DECISION` per section 4 (H6 for `verification failed:`); `RESULT: OK` needs at least one commit in `git -C <wt> log --grep='^PR-Fix: ' <Base commit>..HEAD` (instead of `Plan-Step:`) and a clean tree.
7. **Review.** Spawn `ticket-reviewer` with `REVIEW_SINCE=<Base commit>` and the model choice of section 8. Run the scope check, then format and commit `review.md` as `docs(<KEY>): add review for PR feedback round <n>` plus the trailer (not the section 8 subject, so the rounds stay distinguishable), then **Event `review-done`**. `VERDICT: CHANGES_REQUIRED`: increment `reviewRound`, run one `ticket-dev` `MODE=fix-review` round (section 8), review again; if it still returns `CHANGES_REQUIRED`, ask H5 as in section 8 (**Accept as is**, recorded in `state.warnings` and listed in the summary comment of step 8 · **One more round** · **Take over manually**, leaving `stage: "addressing_review"`).
8. **Verify, push, reply.**
   1. Run the `## Verification` commands of `plan.md` as in section 9a, step 1 (H6 on failure). The tree must be clean; then push with a plain `git -C <wt> push` (never force).
   2. Reply on GitHub. Write each body to a file in the scratchpad and post it with `-F body=@<file>`. Every body starts with the marker line, then a short note: the commit hash(es) (`git log --grep="^PR-Fix: <id>"`) for a `change`, the answer for a `question`, the reason for a `decline`. Skip an item that already has a later marked comment in its thread (for reviews and issue comments: a PR comment containing `PR feedback round <n>`), so a re-run never posts twice.
      - Inline comment: reply in its thread, to the root comment id: `gh api repos/{owner}/{repo}/pulls/{n}/comments/{id}/replies -F body=@<file>`.
      - Review or issue comment: one PR comment for all of them, `gh pr comment <prUrl> --body-file <file>`: the marker line, a heading `PR feedback round <n>`, one line per item (id, outcome), plus any checks skipped or findings accepted in this round (`state.warnings`).
9. **Close.** Set `lastAddressedCommentAt` to the newest `Created` among the items of `pr-feedback-<n>.md` (ISO-8601) and `stage: "done"`. **Event `pr-feedback-addressed`**. Print: PR URL, items by class, commits, replies posted, warnings. Threads stay unresolved and no review is requested; the developer does that. Then go to section 9c. **Take over manually** and **Abort** do not restart the watch.

## 9c. Watch the PR

Stage `done`, PR `OPEN`. The session stays open and wakes itself when there is something to do.

1. Re-read `state.json` and write `updatedAt` (stage unchanged).
2. Start the watcher with the Bash tool and `run_in_background: true`: `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/watch_pr.py" --state <TICKET_DIR>/state.json` (absolute path). It polls the PR about once a minute with `gh`, writes `watch.heartbeatAt` into `state.json`, and ends with one JSON line on stdout.
3. Print one line ("Watching <prUrl>; this session wakes on new feedback, merge or close. Closing it stops the watch; `/ticket <KEY> --resume` restarts it.") and end the turn. Do nothing else while it runs.
4. On wake-up, read the last stdout line of the background command as JSON (`outcome`):
   - `feedback`: section 9b from step 1; it comes back here when done;
   - `merged`: section 9d;
   - `closed`: report that the PR was closed without a merge, stop watching, change nothing else;
   - `error`, a last line that is not JSON, or a killed process: report the message, stop watching, and say that `/ticket <KEY> --resume` restarts the watch.

## 9d. Merge cleanup

Stage `merged`. Runs when the watcher reports `merged`, when section 9b finds the PR merged, and on `--resume` in stage `merged`. Every step can run again safely.

1. Confirm with `gh pr view <prUrl> --json state,mergedAt` that the PR is `MERGED`, then set `stage: "merged"`. Take the PR's head commit from `gh api repos/{owner}/{repo}/pulls/{n} --jq .head.sha` (`gh pr view` has no head-commit field in every `gh` version).
2. Print the final report: PR URL, merge time, worktree path, branch (it is kept), and whether the worktree will be removed (step 4). Then **Event `merged`** (a re-run of this section runs it again, so the rules file should say how to skip work already done).
3. Notify: `bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/hooks/notify.py" "<KEY> merged" "<one line>"`. A failure is ignored; the report is already printed.
4. Remove the worktree, as the very last action, and only when `git -C <wt> status --porcelain` prints nothing (the ignored `state.json` does not count) and `git -C <wt> rev-parse HEAD` equals that head commit; otherwise keep it and say why. If `orca` is on `PATH` and `orca worktree list --repo path:<root> --json --limit 500` has an entry whose `path` equals `<wt>` and whose `isMainWorktree` is false (do not use `ORCA_WORKTREE_ID`): `orca worktree rm --worktree path:<wt> --json`; exit 143 with no output is expected when this session runs inside that worktree. Otherwise: `git -C <root> worktree remove <wt>`. Never pass `--force` or `--delete-branch`, and never delete a branch.

## 10. Abort

On Abort (H2, H6, H7, a restart, or a user request): set `abortedFrom` to the current stage, `stage: "aborted"`, **Event `aborted`**, and **keep** the worktree and branch untouched. Tell the developer the worktree path and that `/ticket <KEY> --resume` continues.
