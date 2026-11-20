# Porting map: gated-dev-simple-workflow

One row per JS test (`test/*.test.mjs`). The last column says where the Python
port lives: `todo`, `dropped: <reason>`, or `<path relative to the plugin>::<test_name>`
(several targets separated by `, `). `tests/test_porting.py` checks that every JS
test has a row and that every target exists.

| JS file | JS test | Python test |
| --- | --- | --- |
| launch.test.mjs | buildShellCommand quotes cwd, sets TICKET_FLOW_KEY and names the session | todo |
| launch.test.mjs | buildShellCommand escapes single quotes in cwd | todo |
| launch.test.mjs | buildShellCommand rejects unsafe keys, other args, relative cwd, bad remoteControl | todo |
| launch.test.mjs | shortSummary strips unsafe characters and cuts at a word boundary | todo |
| launch.test.mjs | sessionName: key, resume and summary | todo |
| launch.test.mjs | a hostile title cannot reach the shell or AppleScript | todo |
| launch.test.mjs | slugify follows the skill rule | todo |
| launch.test.mjs | detectHost: TERM_PROGRAM first, then Orca handle, then iTerm2 session id | todo |
| launch.test.mjs | iTermSessionId takes the GUID and ignores unusable values | todo |
| launch.test.mjs | buildAppleScript escapes, names the tab and targets the launcher's window | todo |
| launch.test.mjs | buildOrcaArgs: selector, then the launcher's workspace, then the path | todo |
| launch.test.mjs | readConfig: defaults, overrides and invalid content | todo |
| launch.test.mjs | checkKey applies keyPattern and the safe character set | todo |
| launch.test.mjs | readTicket: title, front matter base, missing file and missing title | todo |
| launch.test.mjs | listTicketKeys lists ticket dirs whose key matches | todo |
| launch.test.mjs | findRun finds the <KEY>/* worktree, ignores aborted runs, rejects several | todo |
| launch.test.mjs | resolveBase: front matter, config, origin/HEAD, main | todo |
| launch.test.mjs | orcaWorktreeArgs names the worktree and branch after key and title | todo |
| launch.test.mjs | createOrcaWorktree copies local settings and the ticket into the worktree | todo |
| launch.test.mjs | createOrcaWorktree keeps a ticket the base branch carries, reads other JSON shapes | todo |
| launch.test.mjs | createOrcaWorktree rejects output without JSON or without a path | todo |
| launch.test.mjs | launchTab in iTerm2 runs osascript with -e lines targeting the launcher's session | todo |
| launch.test.mjs | launchTab in Orca creates the terminal, then renames it | todo |
| launch.test.mjs | launchTab in Orca: no handle means no rename; a failed rename is only logged | todo |
| launch.test.mjs | launchTicket in Orca: fetch, Orca worktree, tab in that worktree | todo |
| launch.test.mjs | launchTicket in Orca uses front matter base before config and origin/HEAD | todo |
| launch.test.mjs | launchTicket in Orca with an unregistered repo opens in the main checkout | todo |
| launch.test.mjs | launchTicket in iTerm2 opens the main checkout and runs only osascript | todo |
| launch.test.mjs | launchTicket resumes an existing run in its worktree | todo |
| launch.test.mjs | launchTicket resumes a finished run (restarts the PR watch) | todo |
| launch.test.mjs | launchTicket dry run changes nothing and plans the Orca worktree | todo |
| launch.test.mjs | launchTicket outside Orca/iTerm2 fails unless it is a dry run | todo |
| launch.test.mjs | launchTicket: a failing orca worktree create throws and never falls back | todo |
| launch.test.mjs | launchTicket rejects a key outside keyPattern and a ticket without a file | todo |
| launch.test.mjs | launchTicket with orchestratorRules starts a ticket without ticket.md in the main checkout | todo |
| launch.test.mjs | parseArgs: keys or --all, flags, errors | todo |
| launch.test.mjs | main --all --dry-run plans every ticket without a run and reports failures per key | todo |
| launch.test.mjs | main reports a config error and a usage error | todo |
| notify.test.mjs | hooks.json registers notify.sh for Notification | todo |
| notify.test.mjs | silent without TICKET_FLOW_KEY | todo |
| notify.test.mjs | GATED_DEV_NOTIFY=0 turns it off | todo |
| notify.test.mjs | macOS: osascript with key title and the event message | todo |
| notify.test.mjs | Linux: notify-send with key title and the event message | todo |
| notify.test.mjs | Linux without notify-send: silent, exit 0 | todo |
| notify.test.mjs | other OS: silent, exit 0 | todo |
| notify.test.mjs | default message without jq or with bad input | todo |
| notify.test.mjs | a failing notifier does not fail the hook | todo |
| notify.test.mjs | direct mode: title and message from arguments, no TICKET_FLOW_KEY needed | todo |
| watch-pr.test.mjs | a human issue comment newer than the PR creation exits with feedback | todo |
| watch-pr.test.mjs | a review and an inline comment count as feedback | todo |
| watch-pr.test.mjs | the cutoff is lastAddressedCommentAt, else the PR creation time | todo |
| watch-pr.test.mjs | a cutoff written to the file between polls is honoured | todo |
| watch-pr.test.mjs | bots, pipeline replies, empty comments and empty reviews never exit | todo |
| watch-pr.test.mjs | MERGED and CLOSED exit with their outcome | todo |
| watch-pr.test.mjs | MERGED wins over feedback | todo |
| watch-pr.test.mjs | five consecutive gh failures exit with error | todo |
| watch-pr.test.mjs | four failures, a success, four failures do not exit | todo |
| watch-pr.test.mjs | a missing or invalid state.json counts as a failed poll | todo |
| watch-pr.test.mjs | every poll writes the heartbeat and keeps every other field | todo |
| watch-pr.test.mjs | the heartbeat is written after a failed poll too | todo |
| watch-pr.test.mjs | startedAt stays the first poll time while heartbeatAt advances | todo |
| watch-pr.test.mjs | every sleep is 60000 ms and only gh is run | todo |
| watch-pr.test.mjs | a failed heartbeat write is logged and does not stop the watcher | todo |
| watch-pr.test.mjs | main prints one JSON line and returns the exit code per outcome | todo |
| watch-pr.test.mjs | main returns 2 with a usage line for a missing or relative --state | todo |
| watch-pr.test.mjs | parsePrUrl and normalizePr | todo |
| watch-pr.test.mjs | a PR url that cannot be parsed counts as a failed poll | todo |
| watch-pr.test.mjs | the watcher command passes destructive-guard with its defaults | todo |
