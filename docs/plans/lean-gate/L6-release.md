# L6: Docs and release (`destructive-guard` 1.0.0)

> Part of the [lean gate plan](README.md). Depends on: L0–L5 and LJ0.

- `plugins/destructive-guard/README.md` rewrite:
  - what it does: Jev asks before risky Bash/MCP calls; `.env` files are
    blocked for Read/Edit/Write; it never allows or denies;
  - when Jev is configured but does not answer, every gated call asks with a
    warning until it is back (or `GATE_ENABLED=0`);
  - what it no longer does: no rules, no parser; without a key it only blocks
    `.env` files and says so once per session;
  - every warning and what to do about it;
  - env table (kept variables only), what is sent, the question, prompts;
  - Claude Code assumptions from L0 with links and version;
  - known blind spots: scripts a command runs (D4), `.env` calls are never
    judged;
  - migration from 0.8: removed variables, behaviour changes table;
  - "Design decisions and history" section: origin, Python port, class
    refactor, Lean model, this redesign (PR #9 has the earlier summaries:
    merge or copy them first).
- `test_readme.py`: every env name in `lib/` and `hooks/` documented; every
  `jev/*.json` prompt documented; the pack check goes.
- `CLAUDE.md`: the `destructive-guard` section (Jev-only, asks when Jev is
  unavailable, SessionStart hook, model location, conformance test, live
  tests); the "Main vars" list.
- CI: drop `GATE_JEV` from the `jev-live` job and delete the `GATE_JEV`
  variable from the `CI` environment (D2).
- Versions: `destructive-guard` `0.8.x` → `1.0.0` with a new description in
  `plugin.json` and the catalog; bump `metadata.version`.
- `docs/plans/lean-gate.md`: summarised into the README and deleted.
- Manual trial in a real session before tagging: Jev on, Jev with a wrong key,
  no key, Jev endpoint unreachable (every call prompts with a warning; D10
  noise check), `bypassPermissions`.
- `claude plugin validate .`, `jq . .claude-plugin/marketplace.json`,
  `uv run pytest`, `uv run ruff check .`, `lake build --wfail`.

Commit: `destructive-guard 1.0.0: lean gate`.

## Done when

- [ ] `uv run pytest` and `uv run ruff check .` pass
- [ ] `claude plugin validate .` and `jq . .claude-plugin/marketplace.json` pass
- [ ] `cd plugins/destructive-guard/formal && PATH="$HOME/.elan/bin:$PATH" lake build --wfail` passes
- [ ] one commit with the message given above; nothing pushed unless asked
