# L4: `check` skill on the hook path (D5)

> Part of the [lean gate plan](README.md). Depends on: L1, L2.

- `check/dry_run.py`: `effective_config()` → `{enabled, envGuard, log, jev:
  {url, model, timeoutMs, escalateThreshold, prompt, question, ask, apiKey:
  "[set]"|"[missing]"}, sessionWarnings: [...]}`. `check_call()` builds the
  same hook input and calls the hook's decision function in-process (not
  `gate.sh`), returning `{decision, reason, risk, top, warning}`.
- `check/cli.py`: options `--json`, `--config`, `--mcp`, `--cwd`; remove `--jev`
  (Jev is always on). `--cwd` stays: the script scanner reads the scripts from
  it (D4). Passing `--jev` gives a usage error that says it is no longer needed.
- `check/report.py`: text output

  ```text
  Bash: git push --force origin main
  decision: ask
  reason:   jev: destructive p=0.81 risk=0.86
  ```

  or `decision: none (risk 0.04 ≤ 0.5)`, or
  `decision: ask (jev-unavailable: timeout after 1500 ms)` with the warning, or
  `decision: none — warning: call mentions a .env file …`.
- `skills/check/SKILL.md`: every call check sends the redacted call to Jev and
  costs a request; never put secrets in the checked call; a `.env` mention is
  reported as "not sent".
- Tests: `test_check.py` rewritten with `JevMock`; documented invocations must
  pass the gate (the check command line itself mentions no `.env`).

Commit: `Lean gate L4: check skill on Jev`.

## Done when

- [ ] `uv run pytest` and `uv run ruff check .` pass
- [ ] `claude plugin validate .` and `jq . .claude-plugin/marketplace.json` pass
- [ ] `cd plugins/destructive-guard/formal && PATH="$HOME/.elan/bin:$PATH" lake build --wfail` passes
- [ ] one commit with the message given above; nothing pushed unless asked
