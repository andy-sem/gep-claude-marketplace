---
name: check
description: Dry-run a Bash command or MCP tool call through the destructive-guard hook and report whether it would ask and why, or print the effective configuration (gate settings and Jev settings with the API key redacted). Use when the user asks "would the gate ask for X", "why did the gate ask", or when planning which commands will need approval. Never runs the checked command; a call check sends the redacted call to Jev (one request).
---

# destructive-guard: check

Answers what the hook would do, without running anything. It reads the
configuration exactly like the hook (same env variables) and calls the same
decision code. A call check **always contacts Jev** and costs one request, so
never put secrets in the checked call. A call that mentions a `.env` file is
not sent (reported with a warning).

Script: `${CLAUDE_PLUGIN_ROOT}/lib/check.py` (needs Python >= 3.14).

If `python3` on `PATH` is older, the script exits with
`needs Python >= 3.14 (found X.Y at ...)`. Run it with a 3.14 interpreter
instead (for example `python3.14 -I "${CLAUDE_PLUGIN_ROOT}/lib/check.py" ...`)
and tell the user to point `GATE_INFRA_PYTHON` at that interpreter in the
`env` block of `~/.claude/settings.json`, so the hook finds it too.

## Usage

Pass the command to check as **one single-quoted argument**.

```bash
# A Bash command
python3 "${CLAUDE_PLUGIN_ROOT}/lib/check.py" 'git push --force origin main'

# An MCP call: tool name, then its input as one JSON argument
python3 "${CLAUDE_PLUGIN_ROOT}/lib/check.py" --mcp mcp__db__execute_sql '{"query":"DROP TABLE users"}'

# Effective configuration (also the default with no arguments)
python3 "${CLAUDE_PLUGIN_ROOT}/lib/check.py" --config
```

Option: `--json` prints machine-readable output (`decision`, `reason`, `risk`,
`warning`). With several commands to check, run the script once per command.

## Reading the result

- `decision: ask` — the hook would ask. The reason is `jev: <choice> p=… risk=…`,
  or `jev-unavailable: …` when Jev did not answer (a warning is shown too).
- `decision: none` — no decision; Claude Code's own permission rules decide.
  A `warning` explains a skipped `.env` call or a misconfigured setting.

Report the result as-is; never run the checked command as part of this skill.
