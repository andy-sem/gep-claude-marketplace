# destructive-guard

Work in progress. See `docs/plans/gated-dev-simple-workflow.md` at the
repository root for the plan and work packages.

## Install

```text
/plugin install destructive-guard --marketplace gep/gep-claude-marketplace
```

## What it does (0.4.0)

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

- **Read/Edit/Write of env files** (`.env`, `.env.*`, `*.env`) are blocked,
  except `.env.example`. Only the file name is matched, so
  `config.environment.ts` is fine.
- **Fails closed**: an engine error or invalid configuration asks with a
  `gate-config:` reason.
- **Low noise by default**: a command the parser cannot resolve (`$EDITOR
  file`, `eval "$CMD"`, `curl … | bash`) gets no opinion, while the parts it
  can read are still checked (`$EDITOR f; rm -rf x` asks). `GATE_STRICT=1`
  makes such commands ask.
- **Jev classifier** (optional, see below).

Requires Node.js on PATH. `jq` is optional.

## Jev classifier (optional)

Off by default. With `GATE_JEV=1` and `TYPESAFE_API_KEY` set, every Bash
command and MCP call (redacted; commands mentioning `.env` are never sent)
goes to Jev together with the scripts it runs, a context block and a
multiple-choice question. Jev decides when it is confident; the rules decide
otherwise:

| Jev answer | Result |
| --- | --- |
| `ask` choices above `GATE_JEV_ESCALATE_THRESHOLD` (0.5) | ask, even if no rule matched |
| `safe` choices at or above `GATE_JEV_ALLOW_THRESHOLD` (0.95) | no opinion, even if a rule asked |
| in between, error, timeout | the rule result |

Two variables narrow this:

| Variable | Default | Effect |
| --- | --- | --- |
| `GATE_JEV_SCOPE` | `bash,mcp` | Which calls are sent: `bash`, `mcp` or both. Calls left out keep the rule result and make no request. |
| `GATE_JEV_CAN_LIFT` | `1` | `0` stops a confident safe answer from lifting a rule ask, so Jev can only add asks. |

Jev never emits `allow`. An invalid value makes the gate ask with a
`gate-config:` reason.

**Default question** (`jev/destructive.json`): *"Could this call delete,
overwrite or irreversibly change data or resources, on the local machine or
in any remote service?"* with choices `read_only`, `reversible_change`
(safe) and `destructive` (ask). Its examples cover local commands (`rm -rf`,
`git reset --hard`, `git clean`, `stash drop`, force pushes, disks, docker
volumes), infrastructure, SQL and MCP calls in general.

Change it with env variables:

| Variable | Effect |
| --- | --- |
| `GATE_JEV_PROMPT` | `destructive` (default), `cloud-change` (asks before any cloud/infra/database change), or a path to your own prompt JSON |
| `GATE_JEV_INSTRUCTIONS` | Replaces the question text |
| `GATE_JEV_CONTEXT` | Replaces `context.project` (describe your project: what is precious, what is regenerable) |
| `GATE_JEV_POLICY` | Replaces `context.policy` (what needs a person) |

A prompt file has the shape of `jev/destructive.json`: `question` (snake_case
id), `instructions`, `context` (strings), `criteria` (choice → description
and examples), `ask` and `safe` (disjoint lists of choices). An invalid
prompt makes the gate ask with a `gate-config:` reason.

Other variables: `GATE_JEV_URL`, `GATE_JEV_MODEL`, `GATE_JEV_TIMEOUT_MS`,
`GATE_JEV_ALLOW_THRESHOLD`, `GATE_JEV_ESCALATE_THRESHOLD`, `GATE_JEV_LOG`.

## Configuration

Only env variables, no config file is needed. Set them in the `env` block of
`~/.claude/settings.json` for every project, or of a project's
`.claude/settings.json` to override per project:

```json
{ "env": { "GATE_CHECKS": "destructive,postgres", "GATE_DISABLE_RULES": "git-clean" } }
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `GATE_ENABLED` | `1` | `0` turns both hooks off (no node is started). |
| `GATE_CHECKS` | `destructive` | Comma list of built-in packs: `destructive`, `postgres` (any `psql`/`pg_restore`), `terraform` (apply, import, state changes, …). `base` (wrappers, runners, inert programs) is always loaded. `none` loads no pack. |
| `GATE_RULES_FILE` | unset | Your own rules file(s), `:`-separated, loaded after the packs. With `GATE_CHECKS=none` they replace the packs. |
| `GATE_DISABLE_RULES` | unset | Comma list of rule ids to drop (ids are the prefix of the ask reason, e.g. `git-push-force`). |
| `GATE_ENV_GUARD` | `1` | `0` allows Read/Edit/Write of env files. |
| `GATE_STRICT` | `0` | `1` asks on commands the parser cannot resolve. |
| `GATE_LOG` | unset | File to append one JSON line per decision: `ts`, `tool`, `command` (redacted; `null` when it mentions `.env`), `rule` (rule result), `decision` (`ask`/`none`), `reason`. |
| `GATE_RULES` | unset | Deprecated: one rules file replacing every pack. Same as `GATE_CHECKS=none GATE_RULES_FILE=…`; cannot be combined with them. |
| `GATE_JEV`, `GATE_JEV_*`, `TYPESAFE_API_KEY` | off | The Jev layer, see above. |

Booleans accept `0/1`, `true/false`, `yes/no`, `on/off`. Any other value, an
unknown pack, an unknown rule id in `GATE_DISABLE_RULES`, `GATE_CHECKS=none`
without a rules file, or an unreadable/invalid rules file makes every call ask
with a `gate-config:` reason (fail closed) until it is fixed.

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
