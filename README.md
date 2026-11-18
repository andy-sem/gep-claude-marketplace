# Gep Claude Code Marketplace

A Claude Code plugin marketplace for sharing plugins and skills maintained by
Gep. Skills are distributed inside plugins, so each marketplace entry points
to a plugin directory.

## Repository layout

```text
.claude-plugin/
  marketplace.json       # Marketplace catalog
plugins/
  gep-example/
    .claude-plugin/
      plugin.json        # Plugin metadata
    skills/
      example-skill/
        SKILL.md         # Example skill and its instructions
```

The `gep-example` plugin is a small working example and a starting point for
new contributions.

## Install

In Claude Code, add this repository as a marketplace and install the example
plugin:

```text
/plugin marketplace add gep/gep-claude-marketplace
/plugin install gep-example@gep-claude-marketplace
```

After installation, use `/example-skill` to invoke the sample skill.

## Add a plugin or skill

1. Create a directory under `plugins/` for the plugin.
2. Add a `.claude-plugin/plugin.json` manifest with a unique plugin name,
   version, and description.
3. Add the plugin to `.claude-plugin/marketplace.json`, using a relative
   `source` path to its directory.
4. Put skills in `skills/<skill-name>/SKILL.md` within the plugin. Each
   `SKILL.md` needs YAML frontmatter with a `name` and `description`.
5. Keep the plugin and marketplace versions and descriptions up to date, then
   validate the JSON manifests before submitting.

See the example plugin for the expected file and manifest structure. Plugins
can also provide other Claude Code extensions, such as commands, agents, hooks,
and MCP server configuration.
