# Gep Claude Code Marketplace

A Claude Code plugin marketplace for sharing plugins and skills maintained by
Gep.

```text
/plugin marketplace add gep/gep-claude-marketplace
/plugin install <plugin-name>@gep-claude-marketplace
```

## Plugins

| Plugin | What it does |
| --- | --- |
| [`destructive-guard`](plugins/destructive-guard/README.md) | PreToolUse approval gate: asks before destructive commands and MCP calls (local or cloud), blocks `.env` reads. Zero config; tuned with env variables. |
| [`gated-dev-simple-workflow`](plugins/gated-dev-simple-workflow/README.md) | `/ticket`: file-based ticket → spec → plan → dev → review → PR pipeline in a worktree per ticket. Works with or without the gate. |

The two plugins are independent: install either one alone. Together, the
gate protects every session and the workflow treats each gate prompt as a
checkpoint, never as something to work around.

### Destructive Guard: ask before risky commands

Plugin `destructive-guard`. A safety net for every Claude Code session,
whether a person or an agent is driving. Before a Bash command or an MCP tool
call runs, a `PreToolUse` hook sends the call (with secrets redacted) to
**Jev**, a risk classifier. When Jev
judges that the call could delete, overwrite or irreversibly change data or
resources, locally or in a remote service, Claude Code **asks you first**.

- Only ever adds prompts: it never allows or denies a call by itself, so
  your own permission rules still apply.
- If Jev cannot answer (timeout, network, bad answer), it asks you instead
  of guessing.
- Blocks Read/Edit/Write of `.env` files, and never sends a call that
  mentions one.
- Configured only through env variables; needs `TYPESAFE_API_KEY` for
  anything beyond the `.env` guard. Includes `/destructive-guard:check` to
  dry-run a command, and a Lean 4 model that proves the gate's guarantees.
- Needs Python >= 3.14 (standard library only).

```text
/plugin install destructive-guard@gep-claude-marketplace
```

Full description, diagrams and configuration:
[plugins/destructive-guard/README.md](plugins/destructive-guard/README.md).

### Gated Dev Workflow: from ticket to pull request

Plugin `gated-dev-simple-workflow`. A ticket-to-PR pipeline. `/ticket <KEY>`
takes one ticket (a Markdown file, or a Jira issue) and drives it through **spec → plan → dev → review → PR**,
with one subagent per stage, in a git worktree of its own (plain git, Orca or
iTerm2).

- Stops for you at fixed points; **plan approval is always one**.
- After approval it commits, pushes and opens a PR with `gh`, then keeps
  watching the PR: new review feedback starts a follow-up round, a merge
  removes the worktree and notifies you.
- Optional Jira tracker: fetches the issue and moves it To Do → In Progress
  → In Review → Done. `/ticket-flow <PARENT>` works through all subtasks of a
  Jira parent, launching the next ready one as slots free.
- A launcher opens one session per ticket, with desktop notifications when a
  session needs you. Projects can add their own steps at fixed events.
- Needs `git`, `gh` and Python >= 3.14.

```text
/plugin install gated-dev-simple-workflow@gep-claude-marketplace
```

Full description, diagrams and configuration:
[plugins/gated-dev-simple-workflow/README.md](plugins/gated-dev-simple-workflow/README.md).

## Repository layout

```text
.claude-plugin/
  marketplace.json       # Marketplace catalog
plugins/<name>/          # One directory per plugin
```

## Add a plugin

In Claude Code, add this repository as a marketplace:

```text
/plugin marketplace add gep/gep-claude-marketplace
```

1. Create a directory for the plugin.
2. Add a `.claude-plugin/plugin.json` manifest with a unique plugin name,
   version, and description.
3. Add the plugin to `.claude-plugin/marketplace.json`, using a relative
   `source` path to its directory.
4. Put skills in `skills/<skill-name>/SKILL.md` within the plugin. Each
   `SKILL.md` needs YAML frontmatter with a `name` and `description`.
5. Keep the plugin and marketplace versions and descriptions up to date, then
   validate the JSON manifests before submitting.

After a plugin has been added to the catalog, install it with
`/plugin install <plugin-name>@gep-claude-marketplace`. Plugins can also
provide other Claude Code extensions, such as commands, agents, hooks, and MCP
server configuration.
