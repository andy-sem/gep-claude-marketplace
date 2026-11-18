# Gep Claude Code Marketplace

A Claude Code plugin marketplace for sharing plugins and skills maintained by
Gep. The marketplace catalog is intentionally empty until plugins are added.

## Repository layout

```text
.claude-plugin/
  marketplace.json       # Marketplace catalog
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
