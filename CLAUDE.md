# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Claude Code plugin marketplace (`gep-claude-marketplace`). There is no application code, build, or test suite. The repo is a catalog (`.claude-plugin/marketplace.json`) plus plugin directories. The catalog's `plugins` array is empty until plugins are added.

Users consume it with:

```text
/plugin marketplace add gep/gep-claude-marketplace
/plugin install <plugin-name>@gep-claude-marketplace
```

## Validation

There is no build step. Before committing, validate the manifests:

```bash
claude plugin validate .                 # validate marketplace + plugin manifests
jq . .claude-plugin/marketplace.json     # quick JSON syntax check
jq . <plugin-dir>/.claude-plugin/plugin.json
```

## Adding a plugin

Every new plugin touches two places, and they must stay in sync:

1. **Plugin directory** with a `.claude-plugin/plugin.json` manifest containing a unique `name`, `version`, and `description`.
   - Skills go in `skills/<skill-name>/SKILL.md`, with YAML frontmatter that has a `name` and a `description`.
   - Plugins may also ship commands, agents, hooks, and MCP server configuration.
2. **Catalog entry** in `.claude-plugin/marketplace.json` under `plugins`, with a relative `source` path pointing at the plugin directory.

When a plugin changes, bump its version and update its description in both `plugin.json` and its catalog entry. Bump `metadata.version` in `marketplace.json` when the catalog changes.
