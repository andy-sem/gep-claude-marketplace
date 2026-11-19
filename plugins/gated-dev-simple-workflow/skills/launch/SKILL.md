---
name: launch
description: Open one new Claude Code session per ticket, each running /ticket <KEY>, in new Orca or iTerm2 tabs. Use when the user asks to "launch", "open sessions for" or "start in parallel" several tickets, or all ticket files that have no run yet (--all). A ticket with a run is reopened in its worktree with --resume. Only opens tabs; the pipeline itself runs in each new session.
---

# Launch ticket sessions

Script: `${CLAUDE_PLUGIN_ROOT}/scripts/launch.mjs` (needs `node`; opens tabs in
Orca with the `orca` CLI or in iTerm2 with `osascript`).

1. Run a dry run first and show the user what would open:

   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/scripts/launch.mjs" --dry-run KEY-1 KEY-2
   node "${CLAUDE_PLUGIN_ROOT}/scripts/launch.mjs" --dry-run --all
   ```

2. Ask the user to confirm (each tab starts a new Claude session), then run the
   same command without `--dry-run`. Add `--remote-control` only when the user
   asks for it.
3. Report per key what opened (`mode`, `title`) and any error line verbatim.

Modes: `orca-worktree` (a new Orca worktree on branch `<KEY>/<slug>`; the
session adopts it), `main-checkout` (iTerm2, or Orca with a repo Orca does not
know: the session creates its own git worktree), `resume` (the run's worktree,
`/ticket <KEY> --resume`), `skip` (the run is done).

Outside Orca and iTerm2 the script refuses to open tabs (exit 1); `--dry-run`
works anywhere. Never edit ticket files or worktrees from this skill.
