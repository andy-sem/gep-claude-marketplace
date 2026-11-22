# L3: Lean ↔ code traceability

> Part of the [lean gate plan](README.md). Depends on: L0, L1.

Small, separate so it can be reviewed on its own:

- A table at the top of `hook.py`, `jev/judge.py`, `session.py` naming the Lean
  definition each function implements (`hook`, `judge`, `sessionStart`).
- `tests/test_lean_conformance.py` reads the `example` lines from
  `SimpleGate.lean` and fails if an example has no test of the same name (keeps
  model and tests from drifting without needing Lean in the Python CI job).

Commit: `Lean gate L3: model ↔ code cross-references`.

## Done when

- [ ] `uv run pytest` and `uv run ruff check .` pass
- [ ] `claude plugin validate .` and `jq . .claude-plugin/marketplace.json` pass
- [ ] `cd plugins/destructive-guard/formal && PATH="$HOME/.elan/bin:$PATH" lake build --wfail` passes
- [ ] one commit with the message given above; nothing pushed unless asked
