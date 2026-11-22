# L5: `gated-dev-simple-workflow` follow-up (D6)

> Part of the [lean gate plan](README.md). Depends on: L4 (new `check` output). D6 not yet answered: the plan uses option b.

- `agents/ticket-planner.md`: `## Gated operations` columns `Command`, `Gate`,
  `Reason`. `Gate` = `ask (risk 0.86)` from `GATE_CHECK`, or `unknown`. The
  planner always lists calls it judges risky itself; `GATE_CHECK` only fills
  the `Gate` column.
- `skills/ticket/SKILL.md` step 3: set `GATE_CHECK` only when
  `.claude/gated-dev.json` has `"dryRunGate": true`; drop "Never pass `--jev`"
  and `--cwd`.
- `skills/ticket/references/config.md`: document `dryRunGate` next to
  `tracker` and `flow` (default false; each checked call is a Jev request that
  sends the redacted command). `/ticket-flow` runs `/ticket` sessions, so it
  inherits the setting; nothing in `scripts/gated_dev/flow/` calls the gate.
- `README.md` of the workflow: replace the `Rule ID` paragraphs and the
  "If `destructive-guard` moves to the Jev-only design" note.
- `tests/test_watch_pr.py::test_watcher_command_passes_the_gate`: run the
  watcher command through the new hook with `JevMock` answering safe; assert
  no `ask`.
- Version bump of the workflow plugin (`plugin.json` + catalog).

Commit: `gated-dev: gated operations without rule ids`.

## Done when

- [ ] `uv run pytest` and `uv run ruff check .` pass
- [ ] `claude plugin validate .` and `jq . .claude-plugin/marketplace.json` pass
- [ ] `cd plugins/destructive-guard/formal && PATH="$HOME/.elan/bin:$PATH" lake build --wfail` passes
- [ ] one commit with the message given above; nothing pushed unless asked
