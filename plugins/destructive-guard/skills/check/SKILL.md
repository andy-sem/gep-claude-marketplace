---
name: check
description: Dry-run a Bash command or MCP tool call through the destructive-guard approval gate and report whether it would ask, which rule matched and why; or print the gate's effective configuration (packs, disabled rules, strict mode, Jev settings with the API key redacted). Use when the user asks "would the gate ask for X", "why did the gate ask", "what does destructive-guard block", or when planning which commands will need approval. Never runs the checked command.
---

# destructive-guard: check

Answers what the gate would do, without running anything. It loads the
configuration exactly like the hook (same env variables, same packs and rules
files) and calls the same decision code.

Script: `${CLAUDE_PLUGIN_ROOT}/lib/check.py` (needs Python >= 3.14).

If `python3` on `PATH` is older, the script exits with
`needs Python >= 3.14 (found X.Y at ...)`. Run it with a 3.14 interpreter
instead (for example `python3.14 -I "${CLAUDE_PLUGIN_ROOT}/lib/check.py" ...`)
and tell the user to point `GATE_INFRA_PYTHON` at that interpreter in the
`env` block of `~/.claude/settings.json`, so the hook finds it too.

## Usage

Pass the command to check as **one single-quoted argument**. Unquoted, the
words would be parsed by the gate itself as part of your own call and could
make it ask.

```bash
# A Bash command
python3 "${CLAUDE_PLUGIN_ROOT}/lib/check.py" 'git push --force origin main'

# An MCP call: tool name, then its input as one JSON argument
python3 "${CLAUDE_PLUGIN_ROOT}/lib/check.py" --mcp mcp__db__execute_sql '{"query":"DROP TABLE users"}'

# Effective configuration (also the default with no arguments)
python3 "${CLAUDE_PLUGIN_ROOT}/lib/check.py" --config
```

Options (before the command):

| Option | Effect |
| --- | --- |
| `--json` | Machine-readable output (`decision`, `source`, `reason`, `rule`, `jev`) |
| `--cwd DIR` | Resolve scripts the command runs relative to `DIR` (default: current directory) |
| `--jev` | Also ask Jev when `GATE_JEV=1` (sends the redacted call to the configured endpoint). Off by default: the check is local only |

With several commands to check, run the script once per command.

## Reading the result

- `decision: ask` — the gate would ask. `source` is the rule id from a pack
  (e.g. `git-push-force`), or the gate's own tag: `script` (a script the
  command runs), `unparsable`, `gate-config` (configuration error: every
  gated call asks until fixed), `jev`.
- `decision: none` — the gate has no opinion; Claude Code's own permission
  rules decide.
- `rules alone:` — shown when Jev changed the rule result.
- `jev: would be consulted` — Jev is on and in scope for this call, so the
  real hook may answer differently; rerun with `--jev` to see it.

To silence a rule that is too broad, suggest `GATE_DISABLE_RULES=<rule id>`
in the `env` block of `.claude/settings.json` (project) or
`~/.claude/settings.json` (global). Report the result to the user as-is;
never run the checked command as part of this skill.
