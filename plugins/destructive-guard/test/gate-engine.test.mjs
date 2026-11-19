import { test } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import {
  classify,
  loadRules,
  splitCommand,
  RulesError,
  UnparsableError,
  shellScriptIndex,
  stripWrappers,
} from "../lib/gate-engine.mjs"

const rules = {
  wrappers: [
    "env",
    "sudo",
    "time",
    "nohup",
    "command",
    "exec",
    "timeout",
    "xargs",
    "nice",
    "doas",
    "watch",
    "caffeinate",
    "builtin",
    "coproc",
  ],
  runners: [
    {
      program: "npx",
      valueOptions: ["-p"],
      shellOptions: ["-c"],
      bareBin: true,
    },
    { program: "bunx", bareBin: true },
    {
      program: "pnpm",
      valueOptions: ["-C", "--dir", "-F", "--filter"],
      subcommands: ["exec", "dlx", "run"],
      shellOptions: ["--shell-mode"],
      bareBin: true,
    },
    {
      program: "npm",
      valueOptions: ["-w", "--workspace"],
      subcommands: ["exec", "x"],
      shellOptions: ["-c", "--call"],
    },
    {
      program: "yarn",
      valueOptions: ["--cwd"],
      subcommands: ["dlx"],
      bareBin: true,
    },
    ["legacy", "exec"],
  ],
  inertPrograms: ["echo", "which", "rg", "man", "grep"],
  inertUnsafeFlags: { rg: ["--pre"], man: ["-P", "--pager", "-H", "--html"] },
  rules: [
    {
      id: "cloudctl",
      kind: "cli-allowlist",
      programs: ["cloudctl"],
      helpFlags: ["--help", "-h"],
      helpWords: ["help"],
      skipWords: ["preview"],
      readPrefixes: [["version"]],
      readSequences: [
        ["config", "get"],
        ["run", "jobs", "list"],
      ],
      readVerbs: ["list", "describe"],
      writeVerbs: ["create", "delete", "apply", "run", "ssh"],
    },
    {
      id: "blobctl",
      kind: "cli-allowlist",
      programs: ["blobctl"],
      readPrefixes: [["ls"]],
    },
    {
      id: "dbtool",
      kind: "cli-gated",
      programs: ["dbtool"],
      gatedPrefixes: [["push"], ["db", "reset"]],
      unlessFlags: [],
      helpFlags: ["--help"],
    },
    {
      id: "rawsql",
      kind: "cli-gated",
      programs: ["rawsql"],
      gatedPrefixes: [[]],
      unlessFlags: ["--dry"],
    },
    {
      id: "x-mcp",
      kind: "mcp-allowlist",
      tool: "^mcp__x__(.+)$",
      readTools: ["^list_", "^get_"],
    },
    {
      id: "cloudctl-mcp",
      kind: "mcp-as-cli",
      tool: "^mcp__cloud__run$",
      argsField: "args",
      program: "cloudctl",
    },
  ],
}

const ruleSet = loadRulesFromObject(rules)

function loadRulesFromObject(obj) {
  const dir = mkdtempSync(join(tmpdir(), "gate-rules-"))
  const path = join(dir, "rules.json")
  writeFileSync(path, JSON.stringify(obj))
  return loadRules(path)
}

const bash = (command) => ({ tool_name: "Bash", tool_input: { command } })
const mcp = (tool_name, tool_input) => ({ tool_name, tool_input })

function run(c) {
  return classify(typeof c === "string" ? bash(c) : c, ruleSet)
}

const cases = [
  // allowlist
  ["cloudctl things list --project p", null],
  ["cloudctl version", null],
  // Read prefixes/sequences are anchored at the first positional (fail closed):
  // the original plan allowed a sequence anywhere, which let a write command such
  // as `host ssh vm run jobs list` pass. Leading words are no longer skipped.
  ["cloudctl a b config get x", "cloudctl"],
  ["cloudctl things describe t", null],
  ["cloudctl things create t", "cloudctl"],
  ["cloudctl frob", "cloudctl"],
  ["cloudctl things delete list", "cloudctl"],
  // gated
  ["dbtool push", "dbtool"],
  ["dbtool new x", null],
  ['rawsql -c "select 1"', "rawsql"],
  ["rawsql --dry -c x", null],
  // normalization
  ["npx cloudctl things apply", "cloudctl"],
  ["pnpm exec dbtool push", "dbtool"],
  ["/usr/local/bin/cloudctl things apply", "cloudctl"],
  ["env A=1 dbtool push", "dbtool"],
  ["A=1 sudo dbtool push", "dbtool"],
  ["timeout 5 dbtool push", "dbtool"],
  ['bash -c "cloudctl things apply"', "cloudctl"],
  ["echo x | xargs -n1 cloudctl things delete", "cloudctl"],
  // compound
  ["pnpm test && dbtool push", "dbtool"],
  ["ls; echo $(dbtool push)", "dbtool"],
  ["echo `dbtool push`", "dbtool"],
  ["(cd x && dbtool push)", "dbtool"],
  ["git status | head", null],
  // arguments
  ['git commit -m "cloudctl apply; rawsql"', null],
  ['rg "dbtool push" docs', null],
  // mcp
  [mcp("mcp__x__list_items", {}), null],
  [mcp("mcp__x__run_query", {}), "x-mcp"],
  [mcp("mcp__cloud__run", { args: ["things", "list"] }), null],
  [
    mcp("mcp__cloud__run", { args: ["cloudctl", "things", "delete", "a"] }),
    "cloudctl",
  ],
  [mcp("mcp__cloud__run", {}), "unparsable"],
  [mcp("mcp__other__anything", {}), null],
  // robustness: heredocs, redirects, groups, wrappers with option values
  ["git commit -m \"$(cat <<'EOF'\nit's fine; dbtool push\nEOF\n)\"", null],
  ["cat <<EOF\n$(dbtool push)\nEOF", "dbtool"],
  ["dbtool 2>/dev/null push", "dbtool"],
  ["ls 2>&1 | head", null],
  ["if true; then dbtool push; fi", "dbtool"],
  ["{ dbtool push; }", "dbtool"],
  ["sudo -u root bash -c 'dbtool push'", "dbtool"],
  // review round 1: allowlist verbs vs sequences / prefixes / flag values
  ["cloudctl things delete config get", "cloudctl"],
  ["cloudctl config get delete x", null],
  ["cloudctl version apply", "cloudctl"],
  ["cloudctl --format list things delete x", "cloudctl"],
  ["cloudctl things list --project p", null],
  // review round 1: shell options before -c
  ["bash -o pipefail -c 'cloudctl things apply'", "cloudctl"],
  ["bash -O extglob -c 'cloudctl things apply'", "cloudctl"],
  ["bash -ec 'cloudctl things apply'", "cloudctl"],
  // review round 2: option clusters ending in o/O, lone dash
  ["bash -eo pipefail -c 'cloudctl things apply'", "cloudctl"],
  ["bash -lo pipefail -c 'cloudctl things apply'", "cloudctl"],
  ["bash +O extglob -c 'cloudctl things apply'", "cloudctl"],
  ["bash -c -e 'cloudctl things apply'", "cloudctl"],
  ["bash -co pipefail 'cloudctl things apply'", "cloudctl"],
  ["bash -eo pipefail -c 'cloudctl things list'", null],
  ["bash - <<EOF\ncloudctl things apply\nEOF", "cloudctl"],
  ["bash - <<EOF\ncloudctl things list\nEOF", null],
  ["echo cloudctl things apply | bash -", "unparsable"],
  ["bash -s -- a b", "unparsable"],
  // review round 1: shell fed through stdin
  ["bash <<EOF\ndbtool push\nEOF", "dbtool"],
  ["sh <<'EOF'\ndbtool push\nEOF", "dbtool"],
  ["zsh <<< 'dbtool push'", "dbtool"],
  ["bash <<EOF\necho hi\nEOF", null],
  ["echo dbtool push | bash", "unparsable"],
  ["cat f | sh -s", "unparsable"],
  ["sudo bash", "unparsable"],
  ["bash ./local-script.sh", null],
  // review round 1: dynamic nested commands / command words
  ['eval "$CMD"', "unparsable"],
  ['bash -c "$CMD"', "unparsable"],
  ['eval "dbtool push"', "dbtool"],
  ['eval "echo $(dbtool push)"', "dbtool"],
  ["$CMD push", "unparsable"],
  // final review C1: gated prefixes match as an ordered subsequence
  ["dbtool --dir x push", "dbtool"],
  ["dbtool db --url x reset", "dbtool"],
  ["dbtool --workdir a/b db reset", "dbtool"],
  ["dbtool db diff", null],
  ["dbtool dev --port 1", null],
  // final review C1: package-manager runners with options and bare bins
  ["pnpm dbtool push", "dbtool"],
  ["pnpm -C apps/x exec dbtool push", "dbtool"],
  ["pnpm --filter x exec dbtool push", "dbtool"],
  ["pnpm -Fx dbtool push", "dbtool"],
  ["pnpm dlx dbtool@1.2.3 push", "dbtool"],
  ["pnpm exec --shell-mode dbtool push", "dbtool"],
  ["npm exec dbtool push", "dbtool"],
  ["npm exec -- dbtool push", "dbtool"],
  ["npm -w x exec dbtool push", "dbtool"],
  ["npm exec -c 'dbtool push'", "dbtool"],
  ["npx -c 'dbtool push'", "dbtool"],
  ["npx -p dbtool dbtool push", "dbtool"],
  ["yarn dbtool push", "dbtool"],
  ["yarn --cwd x dbtool push", "dbtool"],
  ["legacy exec dbtool push", "dbtool"],
  ["pnpm test", null],
  ["pnpm run build", null],
  ["npm run build", null],
  ["pnpm install", null],
  // final review I1: anchored reads, flag values are not verbs, `--` ends verbs
  ["cloudctl preview config get x", null],
  ["cloudctl run jobs list", null],
  ["cloudctl preview run jobs list", null],
  ["cloudctl host ssh vm run jobs list", "cloudctl"],
  ["cloudctl host ssh vm --command reboot --zone list", "cloudctl"],
  ["cloudctl users set-password u --password list", "cloudctl"],
  ["cloudctl things list --project=p", null],
  ["cloudctl --project p run jobs list", null],
  ["cloudctl --project delete run jobs list", "cloudctl"],
  ["cloudctl things describe -- create", "cloudctl"],
  ["cloudctl config get -- delete", null],
  ["blobctl ls x", null],
  ["blobctl --format=json ls", null],
  ["blobctl -o ls rm x", "blobctl"],
  ["blobctl --dataset ls query x", "blobctl"],
  [
    mcp("mcp__cloud__run", {
      args: ["host", "ssh", "vm", "run", "jobs", "list"],
    }),
    "cloudctl",
  ],
  [
    mcp("mcp__cloud__run", {
      args: ["host", "ssh", "vm", "--command", "reboot", "--zone", "list"],
    }),
    "cloudctl",
  ],
  // final review I2: dynamic arguments to a matched program ask
  ["dbtool $ACTION", "dbtool"],
  ["dbtool $(echo push)", "dbtool"],
  ["dbtool pu$(echo sh)", "dbtool"],
  ["echo push | xargs dbtool", "dbtool"],
  ["find . -exec dbtool {} \\;", "dbtool"],
  ["cloudctl things list --project $P", "cloudctl"],
  ["ls $HOME", null],
  ["echo $(date)", null],
  ['git commit -m "$MSG"', null],
  ["find . -name x | xargs rg foo", null],
  // final review I3: unknown wrappers, programs later in the command, wrappers data
  ["./with-secrets.sh env.enc dbtool push", "dbtool"],
  ["./with-secrets.sh env.enc dbtool db diff", null],
  ["script -q /dev/null dbtool push", "dbtool"],
  ["find . -exec dbtool push \\;", "dbtool"],
  ["./x.sh bash -c 'dbtool push'", "dbtool"],
  ["./x.sh npx -c 'dbtool push'", "dbtool"],
  ["./x.sh cloudctl things create t", "cloudctl"],
  ["./x.sh cloudctl things list", null],
  ["./x.sh rawsql", "rawsql"],
  ["nice dbtool push", "dbtool"],
  ["nice -n 5 dbtool push", "dbtool"],
  ["doas -u root dbtool push", "dbtool"],
  ["caffeinate -t 5 dbtool push", "dbtool"],
  ["builtin command dbtool push", "dbtool"],
  ["coproc dbtool push", "dbtool"],
  ["coproc name dbtool push", "dbtool"],
  ["watch dbtool push", "dbtool"],
  ["watch -n 5 'dbtool push'", "dbtool"],
  ["watch -n 5 'cloudctl things list'", null],
  ["env -S 'dbtool push'", "dbtool"],
  ["env -S'dbtool push'", "dbtool"],
  ["sudo -iu root dbtool push", "dbtool"],
  ["sudo -h dbtool push", "dbtool"],
  ["sudo --user root dbtool push", "dbtool"],
  ["xargs -l dbtool push", "dbtool"],
  ["echo dbtool push", null],
  ["which rawsql", null],
  ["rg rawsql docs", null],
  ["tool run watch $ID", null],
  ["find . -exec rg -l rawsql {} +", null],
  // inert programs that run a command through a flag are not inert
  ["rg --pre rawsql x", "inert program with command flag"],
  ["rg --pre=rawsql x", "inert program with command flag"],
  ["rg -n --pre rawsql x", "inert program with command flag"],
  ["man -P rawsql ls", "inert program with command flag"],
  ["man -Prawsql ls", "inert program with command flag"],
  ["man --pager=rawsql ls", "inert program with command flag"],
  ["man --html=rawsql ls", "inert program with command flag"],
  ["nice rg --pre rawsql x", "inert program with command flag"],
  ["find . -exec rg --pre rawsql x {} +", "inert program with command flag"],
  ["find . -exec man -P rawsql ls \\;", "inert program with command flag"],
  ["man ls", null],
  ["rg --pre-glob '*.gz' foo", null],
  ["find . -exec rg -l x {} \\; -exec dbtool push \\;", "dbtool"],
  ["find . -exec rg -l x {} + -exec dbtool {} \\;", "dbtool"],
  ["ls blob://bucket/rawsql", null],
  // help flags and words pass, unless a flag value or after `--`
  ["cloudctl things create --help", null],
  ["cloudctl things create -h", null],
  ["cloudctl help things create", null],
  ["cloudctl preview help things create", null],
  ["cloudctl --project p help things create", null],
  ["cloudctl --help", null],
  ["cloudctl things create --project=p --help", null],
  ["cloudctl things create --force --help", "cloudctl"],
  ["cloudctl things create -- --help", "cloudctl"],
  ["cloudctl things create --project help", "cloudctl"],
  ["cloudctl things create --help $X", null],
  ["dbtool push --help", null],
  ["dbtool push -h", "dbtool"],
  ["dbtool help push", "dbtool"],
  ["dbtool push --dry --help", "dbtool"],
  ["dbtool push -- --help", "dbtool"],
  ["./x.sh dbtool push --help", null],
  ["./x.sh cloudctl things create --help", null],
  [mcp("mcp__cloud__run", { args: ["things", "create", "--help"] }), null],
  [
    mcp("mcp__cloud__run", { args: ["things", "create", "--", "--help"] }),
    "cloudctl",
  ],
  // fail closed / non-gated
  ['echo "unterminated', "unparsable"],
  [{ tool_name: "Bash", tool_input: {} }, "unparsable"],
  [{ tool_name: "Read", tool_input: { file_path: "/x" } }, null],
]

for (const [c, expected] of cases) {
  const label =
    typeof c === "string" ? c : (c.tool_input?.command ?? JSON.stringify(c))
  test(`classify: ${label} -> ${expected}`, () => {
    const result = run(c)
    assert.equal(result?.reason.split(":")[0] ?? null, expected)
    if (result) assert.equal(result.decision, "ask")
  })
}

test("allowlist reasons name the write verb", () => {
  assert.equal(
    run("cloudctl things delete config get").reason,
    'cloudctl: write verb "delete"',
  )
  assert.equal(
    run("cloudctl version apply").reason,
    'cloudctl: write verb "apply"',
  )
})

test("dynamic arguments name the reason", () => {
  assert.equal(run("dbtool $ACTION").reason, "dbtool: dynamic argument")
  assert.equal(
    run("echo push | xargs dbtool").reason,
    "dbtool: dynamic argument",
  )
})

test("loadRules accepts legacy and object runners and rejects bad ones", () => {
  assert.deepEqual(
    ruleSet.runners.find((r) => r.program === "legacy").subcommands,
    ["exec"],
  )
  const dir = mkdtempSync(join(tmpdir(), "gate-runners-"))
  const p = join(dir, "r.json")
  writeFileSync(p, JSON.stringify({ runners: [{ valueOptions: [] }] }))
  assert.throws(() => loadRules(p), RulesError)
  writeFileSync(p, JSON.stringify({ runners: [{ program: "x", bareBin: 1 }] }))
  assert.throws(() => loadRules(p), RulesError)
})

test("shell reading stdin is unparsable, with a reason", () => {
  assert.equal(run("echo x | bash").reason, "unparsable: shell reads stdin")
  assert.equal(run('eval "$CMD"').reason, "unparsable: dynamic shell command")
})

test("non-object input fails closed", () => {
  assert.equal(classify(null, ruleSet).reason.split(":")[0], "unparsable")
  assert.equal(classify("x", ruleSet).reason.split(":")[0], "unparsable")
})

test("splitCommand returns one token list per simple command", () => {
  assert.deepEqual(splitCommand('a b && c "d e"; f'), [
    ["a", "b"],
    ["c", "d e"],
    ["f"],
  ])
  assert.throws(() => splitCommand('echo "x'), UnparsableError)
  assert.throws(() => splitCommand("(echo x"), UnparsableError)
})

test("loadRules throws RulesError on bad config", () => {
  const dir = mkdtempSync(join(tmpdir(), "gate-bad-"))
  const write = (name, text) => {
    const p = join(dir, name)
    writeFileSync(p, text)
    return p
  }
  assert.throws(() => loadRules(write("a.json", "{not json")), RulesError)
  assert.throws(
    () =>
      loadRules(
        write("b.json", JSON.stringify({ rules: [{ id: "x", kind: "nope" }] })),
      ),
    RulesError,
  )
  assert.throws(
    () =>
      loadRules(
        write(
          "c.json",
          JSON.stringify({
            rules: [{ id: "x", kind: "mcp-allowlist", tool: "(" }],
          }),
        ),
      ),
    RulesError,
  )
  assert.throws(() => loadRules(join(dir, "missing.json")), RulesError)
})

test("loadRules ignores a leftover protectedBranches and rejects removed kinds", () => {
  const dir = mkdtempSync(join(tmpdir(), "gate-legacy-"))
  const p = join(dir, "r.json")
  writeFileSync(p, JSON.stringify({ protectedBranches: ["main"], rules: [] }))
  assert.deepEqual(loadRules(p).rules, [])
  for (const kind of ["script", "git-push"]) {
    writeFileSync(
      p,
      JSON.stringify({ rules: [{ id: "x", kind, pathPattern: "x" }] }),
    )
    assert.throws(() => loadRules(p), RulesError, kind)
  }
})

test("loadRules fails closed on a malformed inertUnsafeFlags", () => {
  const dir = mkdtempSync(join(tmpdir(), "gate-inert-"))
  const p = join(dir, "r.json")
  for (const bad of [
    "rg",
    ["--pre"],
    null,
    { rg: "--pre" },
    { rg: [1] },
    { rg: [""] },
  ]) {
    writeFileSync(p, JSON.stringify({ inertUnsafeFlags: bad }))
    assert.throws(() => loadRules(p), RulesError, JSON.stringify(bad))
  }
  writeFileSync(p, JSON.stringify({ inertUnsafeFlags: { rg: ["--pre"] } }))
  assert.deepEqual(loadRules(p).inertUnsafeFlags, { rg: ["--pre"] })
})

// CLI entry
const enginePath = fileURLToPath(new URL("../lib/gate-engine.mjs", import.meta.url))

function runCli(stdin, env = {}) {
  const r = spawnSync("node", [enginePath], {
    input: stdin,
    encoding: "utf8",
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: process.cwd(),
      GATE_JEV: "",
      GATE_JEV_LOG: "",
      ...env,
    },
  })
  return {
    status: r.status,
    out: r.stdout.trim() ? JSON.parse(r.stdout) : null,
  }
}

const rulesPath = (() => {
  const dir = mkdtempSync(join(tmpdir(), "gate-cli-"))
  const p = join(dir, "rules.json")
  writeFileSync(p, JSON.stringify(rules))
  return p
})()

test("CLI: emits ask for a gated command and exits 0", () => {
  const { status, out } = runCli(
    JSON.stringify({
      tool_name: "Bash",
      tool_input: { command: "dbtool push" },
      cwd: process.cwd(),
    }),
    { GATE_RULES: rulesPath },
  )
  assert.equal(status, 0)
  assert.equal(out.hookSpecificOutput.hookEventName, "PreToolUse")
  assert.equal(out.hookSpecificOutput.permissionDecision, "ask")
  assert.match(out.hookSpecificOutput.permissionDecisionReason, /^dbtool:/)
})

test("CLI: prints nothing for a non-gated command", () => {
  const { status, out } = runCli(
    JSON.stringify({
      tool_name: "Bash",
      tool_input: { command: "ls" },
      cwd: process.cwd(),
    }),
    { GATE_RULES: rulesPath },
  )
  assert.equal(status, 0)
  assert.equal(out, null)
})

test("CLI: subagent calls (agent_id) still get ask", () => {
  const { status, out } = runCli(
    JSON.stringify({
      tool_name: "Bash",
      tool_input: { command: "dbtool push" },
      cwd: process.cwd(),
      agent_id: "agent-123",
    }),
    { GATE_RULES: rulesPath },
  )
  assert.equal(status, 0)
  assert.equal(out.hookSpecificOutput.permissionDecision, "ask")
})

test("CLI: broken rules file asks with gate-config for every call", () => {
  const dir = mkdtempSync(join(tmpdir(), "gate-cli-bad-"))
  const p = join(dir, "bad.json")
  writeFileSync(p, "{not json")
  const { status, out } = runCli(
    JSON.stringify({
      tool_name: "Read",
      tool_input: { file_path: "/x" },
      cwd: process.cwd(),
    }),
    { GATE_RULES: p },
  )
  assert.equal(status, 0)
  assert.equal(out.hookSpecificOutput.permissionDecision, "ask")
  assert.match(out.hookSpecificOutput.permissionDecisionReason, /^gate-config:/)
})

test("CLI: unparsable stdin asks (fails closed)", () => {
  const { status, out } = runCli("not json", { GATE_RULES: rulesPath })
  assert.equal(status, 0)
  assert.equal(out.hookSpecificOutput.permissionDecision, "ask")
  assert.match(out.hookSpecificOutput.permissionDecisionReason, /^unparsable:/)
})
