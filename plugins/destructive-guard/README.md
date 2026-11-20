# destructive-guard

A deterministic approval gate for Claude Code. A `PreToolUse` hook parses
every Bash command and MCP tool call and **asks you first** when the call
would delete, overwrite or irreversibly change data or resources, on the
local machine or in a remote service. It needs no configuration; everything
is tunable through env variables.

- **Asks, never allows.** The gate either asks or has no opinion; Claude
  Code's normal permission rules apply to everything else.
- **Parses, does not grep.** `echo rm -rf /` or a commit message that
  mentions `git push --force` pass; `sudo xargs rm -rf`, `bash -c '…'` and
  `npx … ` wrappers are seen through.
- **Fails closed.** An engine error or invalid configuration asks with a
  `gate-config:` reason instead of letting calls through.
- **Optional Jev classifier** for what static rules cannot see (off by default).

## Install

```text
/plugin marketplace add gep/gep-claude-marketplace
/plugin install destructive-guard@gep-claude-marketplace
```

Install it once at user scope to protect every session. Requires **Node.js**
on `PATH` (without it, every gated call asks). `jq` is optional.

## What it asks on

| Area | Asks on |
| --- | --- |
| Filesystem | `rm` recursive + force (`-rf`, `-fr`, `-r -f`, `--recursive --force`), `find -delete`, `shred`, `dd of=`, `mkfs*`/`wipefs`, `truncate`, `diskutil erase*` |
| Git | `push --force/-f/--force-with-lease/--mirror/--delete/--prune`, `push +ref` / `push :ref`, `reset --hard`, `clean -f` (not `-n`), `branch -D`, `checkout .`, `restore .` (not `--staged`), `stash drop/clear`, `filter-branch`/`filter-repo`, `update-ref -d` |
| GitHub CLI | `gh … delete` (repo, release, secret, variable, cache, run, gist, label, keys), `pr close/merge --delete-branch`, `gh api -X DELETE` |
| Infra | `terraform/tofu destroy`, `apply -destroy`, `state rm`, `workspace delete`; `kubectl delete/drain`; `helm uninstall`; `docker … prune`, `volume rm`, `compose down -v` |
| Cloud CLIs | `aws … delete-*/terminate-*/…`, `aws s3 rm/rb`, `az … delete/purge`, `wrangler … delete` |
| SQL | `DROP …`, `TRUNCATE`, `DELETE` without `WHERE`, `ALTER TABLE … DROP` in `psql`/`mysql`/`mariadb`/`sqlite3`/`duckdb` arguments or heredocs, and `wrangler d1 execute` |
| MCP tools | tool names with a word like delete/drop/destroy/remove/reset/truncate/purge/wipe/erase/terminate; SQL tools (`*sql*`, `*query*`, `*execute*`) whose input contains destructive SQL |
| Env files | Read/Edit/Write of `.env`, `.env.*`, `*.env` is **blocked** (not asked), except `.env.example`. Only the file name is matched, so `config.environment.ts` is fine. |

Creating or deploying is not destructive by itself; add the `postgres` or
`terraform` pack, or the `cloud-change` Jev prompt, to gate those too.

A command the parser cannot resolve (`$EDITOR file`, `eval "$CMD"`,
`curl … | bash`) gets no opinion, while the parts it can read are still
checked (`$EDITOR f; rm -rf x` asks). `GATE_STRICT=1` makes such commands ask.

**Not caught by the rules:** destructive commands inside a script the
command runs (`bash cleanup.sh` running `rm -rf`), `psql -f file.sql`, SQL
piped into a client. The Jev layer sees these (it receives the scripts).

## Configuration

Only env variables; no config file is needed. Set them in the `env` block of
`~/.claude/settings.json` for every project, or of a project's
`.claude/settings.json` to override per project:

```json
{ "env": { "GATE_CHECKS": "destructive,postgres", "GATE_DISABLE_RULES": "git-clean" } }
```

**Paths.** File variables (`GATE_RULES_FILE`, `GATE_RULES`, `GATE_LOG`,
`GATE_JEV_PROMPT` as a file, `GATE_JEV_LOG`) take absolute paths or paths
relative to the project: `CLAUDE_PROJECT_DIR` (Claude Code sets it for hooks),
else the git root of the current directory. So a project can commit its own
rules next to its code and keep working after the session `cd`s into a
subdirectory:

```json
{ "env": { "GATE_CHECKS": "none", "GATE_RULES_FILE": ".claude/gate-rules.json" } }
```

### Gate

| Variable | Default | Meaning |
| --- | --- | --- |
| `GATE_ENABLED` | `1` | `0` turns both hooks off (no node is started). |
| `GATE_CHECKS` | `destructive` | Comma list of built-in packs: `destructive`, `postgres` (any `psql`/`pg_restore`), `terraform` (apply, import, state changes, …). `base` (wrappers, runners, inert programs) is always loaded. `none` loads no pack. |
| `GATE_RULES_FILE` | unset | Your own rules file(s), `:`-separated, loaded after the packs (see [Writing rules](#writing-rules)). With `GATE_CHECKS=none` they replace the packs. |
| `GATE_DISABLE_RULES` | unset | Comma list of rule ids to drop. The id is the prefix of the ask reason (`git-push-force: gated invocation`) and the `source` of `/destructive-guard:check`. |
| `GATE_ENV_GUARD` | `1` | `0` allows Read/Edit/Write of env files. |
| `GATE_STRICT` | `0` | `1` asks on commands the parser cannot resolve. |
| `GATE_LOG` | unset | File to append one JSON line per decision: `ts`, `tool`, `command` (redacted; `null` when it mentions `.env`), `rule` (rule result), `decision` (`ask`/`none`), `reason`. |
| `GATE_RULES` | unset | Deprecated: one rules file replacing every pack. Same as `GATE_CHECKS=none GATE_RULES_FILE=…`; cannot be combined with them. |

### Jev layer

| Variable | Default | Meaning |
| --- | --- | --- |
| `GATE_JEV` | `0` | `1` sends calls to Jev (see below). |
| `TYPESAFE_API_KEY` | unset | Required when `GATE_JEV=1`. Sent only as a bearer token. |
| `GATE_JEV_URL` | `https://api.typesafe.ai/v1/systemone` | Endpoint. Must be `https` (plain `http` only to `localhost`/`127.0.0.1`/`[::1]`). |
| `GATE_JEV_MODEL` | `jev-latest` | Model name sent with the request. |
| `GATE_JEV_TIMEOUT_MS` | `1500` | Total time budget including retries on 429/529, 1–30000. On timeout the rule result stands. |
| `GATE_JEV_ESCALATE_THRESHOLD` | `0.5` | Ask when the `ask` choices together exceed this. |
| `GATE_JEV_ALLOW_THRESHOLD` | `0.95` | No opinion (lifts a rule ask) when the `safe` choices together reach this. |
| `GATE_JEV_SCOPE` | `bash,mcp` | Which calls are sent: `bash`, `mcp` or both. Calls left out keep the rule result and make no request. |
| `GATE_JEV_CAN_LIFT` | `1` | `0` stops a confident safe answer from lifting a rule ask, so Jev can only add asks. |
| `GATE_JEV_PROMPT` | `destructive` | Built-in prompt (`destructive`, `cloud-change`) or a path to your own prompt JSON. |
| `GATE_JEV_INSTRUCTIONS` | unset | Replaces the prompt's question text. |
| `GATE_JEV_CONTEXT` | unset | Replaces `context.project` (describe your project: what is precious, what is regenerable). |
| `GATE_JEV_POLICY` | unset | Replaces `context.policy` (what needs a person). |
| `GATE_JEV_LOG` | unset | File to append one JSON line per Jev decision: what was sent, probabilities, rule and final decision, token usage, latency, or the fallback reason. |

Booleans accept `0/1`, `true/false`, `yes/no`, `on/off`. Any other value, an
unknown pack, an unknown rule id in `GATE_DISABLE_RULES`, `GATE_CHECKS=none`
without a rules file, an unreadable/invalid rules or prompt file, or
`GATE_JEV=1` without a key makes every call ask with a `gate-config:` reason
(fail closed) until it is fixed.

## Checking a call: `/destructive-guard:check`

Ask Claude *"would the gate ask for `git push --force`?"* or run the skill
directly. It dry-runs a call through the effective configuration (same env
variables, packs and rules files as the hook) and never runs it:

```text
$ node lib/check.mjs 'git push --force origin main'
Bash: git push --force origin main
decision: ask
source:   git-push-force
reason:   git-push-force: gated invocation
jev:      off
```

`--mcp <tool> '<json>'` checks an MCP call, `--config` (or no argument)
prints the effective configuration with the Jev API key redacted, `--json`
gives machine-readable output, `--cwd DIR` resolves scripts relative to DIR.
Jev is not contacted unless you pass `--jev`. `source` is the rule id to put
in `GATE_DISABLE_RULES` if a rule is too broad for you.

## Jev classifier (optional)

Off by default. With `GATE_JEV=1` and `TYPESAFE_API_KEY` set, every call in
`GATE_JEV_SCOPE` goes to Jev with a multiple-choice question. Jev decides
when it is confident; the rules decide otherwise:

| Jev answer | Result |
| --- | --- |
| `ask` choices above `GATE_JEV_ESCALATE_THRESHOLD` | ask, even if no rule matched |
| `safe` choices at or above `GATE_JEV_ALLOW_THRESHOLD` | no opinion, even if a rule asked (unless `GATE_JEV_CAN_LIFT=0`) |
| in between, error, timeout | the rule result |

Jev never emits `allow`. Fail-closed cases (configuration errors, unparsable
hook input) always ask and are never sent.

### What is sent

One HTTPS `POST` per call, with `authorization: Bearer $TYPESAFE_API_KEY`
and a JSON body:

- `model`, and the prompt: question id, instructions and criteria
  (choices with descriptions and examples).
- `state.context`: the prompt's `project` and `policy` text.
- For Bash: the **command** (redacted, at most 8000 characters) and the
  **scripts it runs** that the gate could read inside the project (redacted,
  64 KB in total; lines mentioning `.env` removed), plus notes on what was
  cut or could not be read.
- For MCP: the **tool name** and its **input** as JSON (redacted, at most
  8000 characters; SQL string literals and dollar-quoted bodies replaced).

Redaction replaces credentials in URLs (`https://user:pass@`), `Bearer`/
`Basic`/`Token` values, values of secret-looking names (containing
`token`, `password`/`pwd`, `secret`, `api_key`, `auth…`, `credential`,
`private_key`) as `NAME=…`, `NAME: …`, `--password …` or JSON keys, all
shell env assignments, long hex strings and long base64-like runs. **A Bash command that mentions an `.env` file is never
sent**; the rule result stands. Nothing else (no file you did not run, no
conversation text) leaves the machine.

### The question

Default (`jev/destructive.json`): *"Could this call delete, overwrite or
irreversibly change data or resources, on the local machine or in any remote
service?"* with choices `read_only`, `reversible_change` (safe) and
`destructive` (ask). `GATE_JEV_PROMPT=cloud-change` asks before any change to
cloud resources, infrastructure or databases instead.

A prompt file has the shape of `jev/destructive.json`: `question` (snake_case
id), `instructions`, `context` (`project`, `policy` strings), `criteria`
(choice → description and examples), and `ask` and `safe` (disjoint lists of
choices that together cover every criterion).

## Writing rules

Point `GATE_RULES_FILE` at a JSON file. It is merged with the selected packs:
string lists are concatenated, `rules` are appended, and a rule id may be
defined only once across all files (drop a built-in one with
`GATE_DISABLE_RULES` and redefine it).

```json
{
  "rules": [
    {
      "id": "deploy-prod",
      "kind": "cli-gated",
      "programs": ["make"],
      "gatedPrefixes": [["deploy"], ["release"]],
      "whenArgs": ["^ENV=prod"]
    },
    {
      "id": "kafka-topics-delete",
      "kind": "cli-gated",
      "programs": ["kafka-topics", "kafka-topics.sh"],
      "gatedPrefixes": [[]],
      "whenFlags": [["--delete"]]
    },
    {
      "id": "tracker-writes",
      "kind": "mcp-pattern",
      "tool": "^mcp__tracker__",
      "toolWords": ["edit", "transition", "delete"]
    }
  ]
}
```

Check a new rule with `/destructive-guard:check` before relying on it.

### Rule kinds

| Kind | Asks when |
| --- | --- |
| `cli-gated` | A program in `programs` is called and its positional words contain one of `gatedPrefixes` in order (`[[]]` = any call), narrowed by the fields below. |
| `cli-allowlist` | A program in `programs` is called with anything but a known read: `readPrefixes` / `readSequences` (word lists anchored after `skipWords`) or a `readVerbs` word pass, unless a `writeVerbs` word appears. Use it to gate everything a CLI does except reads. |
| `mcp-pattern` | An MCP call matches `tool` (regex on the full name), `toolWords` (any word of the name after the last `__`, split on `_`, `-` and camelCase) and `inputPattern` (case-insensitive regex over every string in the input). All given conditions must hold. |
| `mcp-allowlist` | An MCP tool matches `tool` (a regex whose first group captures the tool suffix) and the suffix matches none of `readTools`. |
| `mcp-as-cli` | An MCP tool matching `tool` takes a command line in the string array `argsField`; it is checked as a `program` call against the CLI rules. |

`cli-gated` fields:

| Field | Meaning |
| --- | --- |
| `whenFlags` | List of flag groups; every group needs one present flag (`[["-r","-R"],["-f"]]`). |
| `shortBundles` | One-letter flags also match inside bundles (`-rf`, `-fdx`); also applies to `unlessFlags`. |
| `whenArgs` | Regexes; at least one argument must match (`ignoreCase` for `i`, `matchStdin` to include heredocs). |
| `unlessFlags` | Flags that exempt the call (`--dry-run`). |
| `helpFlags`, `helpWords` | Help calls (`--help`, `help`) that are never gated. |
| `dynamicArgs` | `ask` (default): any `$VAR` argument asks. `ignore`: decide on the literal words. |
| `scriptScan` | `false` keeps the program out of the script scanner (below). |

Top-level keys besides `rules`:

| Key | Meaning |
| --- | --- |
| `wrappers` | Programs that run their arguments (`sudo`, `xargs`, …); the wrapped command is checked. |
| `runners` | Package runners (`npx`, `pnpm exec`, …): `program`, `subcommands`, `valueOptions` (options that take a value), `shellOptions` (`-c`), `bareBin`. |
| `inertPrograms` | Programs that never change anything; `inertUnsafeFlags` (`{ "rg": ["--pre"] }`) lists the flags that make them unsafe. |
| `scriptPatterns` | Regexes: a project script the command runs that matches one asks. |
| `scriptScanExempt` | Globs of project scripts the scanner skips. |

The script scanner reads scripts a Bash command runs inside the project
(`bash x.sh`, `node x.mjs`, `pnpm run <script>`, …) and asks when one calls a
program named by a CLI rule (unless `scriptScan: false`), matches
`scriptPatterns`, or cannot be read. The built-in destructive rules opt out
of it, so it is quiet by default; your own rules take part unless they set
`scriptScan: false`.

## Troubleshooting

- **Why did it ask?** The reason starts with the rule id. Run
  `/destructive-guard:check '<command>'`, or set `GATE_LOG=/tmp/gate.jsonl`.
- **A rule is too broad.** Add its id to `GATE_DISABLE_RULES`.
- **Everything asks with `gate-config:`.** The configuration is invalid; the
  reason names the variable or file. `/destructive-guard:check --config`
  prints what the gate sees.
- **Turn it off for one project:** `"GATE_ENABLED": "0"` in that project's
  `.claude/settings.json` `env`.

## Development

```bash
node --test 'plugins/destructive-guard/test/*.test.mjs'
```

| Path | What |
| --- | --- |
| `hooks/hooks.json` | `Bash\|mcp__.*` → `gate.sh`; `Read\|Edit\|Write` → `env-guard.sh` |
| `hooks/gate.sh` | Fail-closed wrapper around the engine (no node or no result → ask) |
| `hooks/env-guard.sh` | Env-file guard |
| `lib/config.mjs` | Env → effective configuration, pack composition |
| `lib/gate-engine.mjs` | Shell parser, rule evaluation, hook entry point |
| `lib/gate-scripts.mjs` | Script collection and scanning |
| `lib/gate-jev.mjs` | Jev configuration, prompts, redaction, request |
| `lib/check.mjs` | Dry-run CLI behind the `check` skill |
| `packs/*.json` | Built-in rule packs |
| `jev/*.json` | Built-in Jev prompts |
