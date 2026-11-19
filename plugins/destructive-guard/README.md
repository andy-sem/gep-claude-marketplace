# destructive-guard

Work in progress. See `docs/plans/gated-dev-simple-workflow.md` at the
repository root for the plan and work packages.

## Install

```text
/plugin install destructive-guard --marketplace gep/gep-claude-marketplace
```

## What it does (0.2.0)

Out of the box, with no configuration, it asks before **destructive** calls:
anything that deletes, overwrites or irreversibly changes data or resources,
locally or in a remote service. Everything else gets no opinion from the gate
(Claude Code's normal permissions apply). The gate never auto-allows.

| Area | Asks on |
| --- | --- |
| Filesystem | `rm` recursive + force (`-rf`, `-fr`, `-r -f`, `--recursive --force`), `find -delete`, `shred`, `dd of=`, `mkfs*`/`wipefs`, `truncate`, `diskutil erase*` |
| Git | `push --force/-f/--force-with-lease/--mirror/--delete/--prune`, `push +ref` / `push :ref`, `reset --hard`, `clean -f` (not `-n`), `branch -D`, `checkout .`, `restore .` (not `--staged`), `stash drop/clear`, `filter-branch`/`filter-repo`, `update-ref -d` |
| GitHub CLI | `gh … delete` (repo, release, secret, variable, cache, run, gist, label, keys), `pr close/merge --delete-branch`, `gh api -X DELETE` |
| Infra | `terraform/tofu destroy`, `apply -destroy`, `state rm`, `workspace delete`; `kubectl delete/drain`; `helm uninstall`; `docker … prune`, `volume rm`, `compose down -v` |
| Cloud CLIs | `aws … delete-*/terminate-*/…`, `aws s3 rm/rb`, `az … delete/purge`, `wrangler … delete` |
| SQL | `DROP …`, `TRUNCATE`, `DELETE` without `WHERE`, `ALTER TABLE … DROP` in `psql`/`mysql`/`mariadb`/`sqlite3`/`duckdb` arguments or heredocs, and `wrangler d1 execute` |
| MCP tools | tool names with a word like delete/drop/destroy/remove/reset/truncate/purge/wipe/erase/terminate; SQL tools (`*sql*`, `*query*`, `*execute*`) whose input contains destructive SQL |

Commands are parsed, not grepped: wrappers (`sudo`, `env`, `xargs`, …),
runners (`npx`, `pnpm exec`, …), `bash -c`, `find -exec` and pipelines are
seen through, while `echo rm -rf /` or a commit message mentioning
`git push --force` pass.

Also:

- **Read/Edit/Write of `.env*` files** are blocked (except `.env.example`).
- **Fails closed**: an engine or config error, an unparsable command, or a
  command whose program is a variable (`$EDITOR file`) asks.
- **Jev classifier** (optional): off unless `GATE_JEV=1` (needs
  `TYPESAFE_API_KEY`). Its prompt asks whether a call changes cloud services,
  remote infrastructure or databases.

Requires Node.js on PATH. `jq` is optional.

## Configuration (so far)

Env-based tuning (`GATE_CHECKS`, `GATE_DISABLE_RULES`, `GATE_ENABLED`, …)
arrives in the next release. Today:

- `GATE_RULES=/path/rules.json` replaces the default packs with one rules
  file. Shipped packs: `packs/base.json`, `packs/destructive.json`, and the
  optional `packs/postgres.json`, `packs/terraform.json`.
- `GATE_JEV=1` and `GATE_JEV_*` enable the Jev layer.

### Rule fields

`cli-gated` rules match a program (`programs`) whose positional words
contain one of `gatedPrefixes` in order, then narrow with:

| Field | Meaning |
| --- | --- |
| `whenFlags` | List of flag groups; every group needs one present flag (`[["-r","-R"],["-f"]]`). |
| `shortBundles` | One-letter flags also match inside bundles (`-rf`, `-fdx`); also applies to `unlessFlags`. |
| `whenArgs` | Regexes; at least one argument must match (`ignoreCase` for `i`, `matchStdin` to include heredocs). |
| `unlessFlags` | Flags that exempt the call (`--dry-run`). |
| `dynamicArgs` | `ask` (default): any `$VAR` argument asks. `ignore`: decide on the literal words. |
| `scriptScan` | `false` keeps the program out of the script scanner's "script runs X" check. |

`mcp-pattern` rules match MCP calls by `tool` (regex on the full name),
`toolWords` (words of the name after the last `__`, split on `_`, `-` and
camelCase) and `inputPattern` (case-insensitive regex over every string in
the input); all given conditions must hold.

## Development

```bash
node --test 'plugins/destructive-guard/test/*.test.mjs'
```
