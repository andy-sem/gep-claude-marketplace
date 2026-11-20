import { test } from "node:test"
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { checkCall, effectiveConfig, parseArgs, run } from "../lib/check.mjs"

const here = dirname(fileURLToPath(import.meta.url))
const cli = join(here, "..", "lib", "check.mjs")
const engine = join(here, "..", "lib", "gate-engine.mjs")

const bash = (command) => ({ mode: "bash", command })
const mcp = (tool, input = {}) => ({ mode: "mcp", tool, input })

test("parseArgs: command, MCP call, config and options", () => {
  assert.deepEqual(parseArgs(["git push -f"]).command, "git push -f")
  assert.equal(parseArgs(["--", "rm", "-rf", "x"]).command, "rm -rf x")
  const m = parseArgs(["--json", "--mcp", "mcp__db__q", '{"a":1}'])
  assert.equal(m.mode, "mcp")
  assert.equal(m.json, true)
  assert.deepEqual(m.input, { a: 1 })
  assert.deepEqual(parseArgs(["--mcp", "mcp__x__y"]).input, {})
  assert.equal(parseArgs([]).mode, "config")
  assert.equal(parseArgs(["--config"]).mode, "config")
  const o = parseArgs(["--jev", "--cwd", "/tmp", "ls"])
  assert.equal(o.jev, true)
  assert.equal(o.cwd, "/tmp")
})

test("run: usage errors exit 2", async () => {
  for (const argv of [
    ["--nope"],
    ["--mcp"],
    ["--mcp", "Bash"],
    ["--mcp", "mcp__x__y", "{"],
    ["--mcp", "mcp__x__y", "[1]"],
    ["--cwd"],
    ["--"],
  ]) {
    const r = await run(argv, { env: {} })
    assert.equal(r.code, 2, JSON.stringify(argv))
    assert.match(r.out, /^usage error: /)
  }
})

test("checkCall with default packs: sample commands", async () => {
  const cases = [
    [bash("ls -la"), "none", null],
    [bash("git status"), "none", null],
    [bash("git push origin main"), "none", null],
    [bash("git push -f origin main"), "ask", "git-push-force"],
    [bash("rm -rf build"), "ask", "rm-recursive-force"],
    [mcp("mcp__db__drop_table", { table: "x" }), "ask", "mcp-destructive-tool"],
    [mcp("mcp__db__execute_sql", { query: "DROP TABLE x" }), "ask", "mcp-destructive-sql"],
    [mcp("mcp__db__execute_sql", { query: "SELECT 1" }), "none", null],
  ]
  for (const [call, decision, source] of cases) {
    const r = await checkCall(call, { env: {} })
    assert.equal(r.decision, decision, JSON.stringify(call))
    assert.equal(r.source, source, JSON.stringify(call))
    assert.equal(r.jev, "off")
  }
})

test("checkCall honours GATE_DISABLE_RULES, GATE_ENABLED and GATE_CHECKS", async () => {
  const push = bash("git push -f")
  assert.equal((await checkCall(push, { env: { GATE_DISABLE_RULES: "git-push-force" } })).decision, "none")
  const off = await checkCall(push, { env: { GATE_ENABLED: "0" } })
  assert.equal(off.decision, "none")
  assert.match(off.reason, /disabled/)
  const tf = bash("terraform apply")
  assert.equal((await checkCall(tf, { env: {} })).decision, "none")
  const r = await checkCall(tf, { env: { GATE_CHECKS: "destructive,terraform" } })
  assert.equal(r.decision, "ask")
})

test("checkCall reports config errors as gate-config asks", async () => {
  for (const env of [
    { GATE_CHECKS: "nope" },
    { GATE_STRICT: "maybe" },
    { GATE_DISABLE_RULES: "no-such-rule" },
    { GATE_CHECKS: "none", GATE_RULES_FILE: "/nonexistent/rules.json" },
  ]) {
    const r = await checkCall(bash("ls"), { env })
    assert.equal(r.decision, "ask", JSON.stringify(env))
    assert.equal(r.source, "gate-config")
  }
})

test("checkCall never contacts Jev without --jev, and says when it would", async () => {
  // An unreachable URL: a request would only change the timing, never the answer,
  // so assert on the reported mode instead.
  const env = {
    GATE_JEV: "1",
    TYPESAFE_API_KEY: "k",
    GATE_JEV_URL: "http://127.0.0.1:1/v1",
  }
  const r = await checkCall(bash("git push -f"), { env })
  assert.equal(r.source, "git-push-force")
  assert.equal(r.jev, "would be consulted (pass --jev)")
  const scoped = await checkCall(bash("ls"), { env: { ...env, GATE_JEV_SCOPE: "mcp" } })
  assert.equal(scoped.jev, "off")
})

test("effectiveConfig: defaults, rule ids, Jev redaction, errors", async () => {
  const c = await effectiveConfig({})
  assert.deepEqual(c.packs, ["base", "destructive"])
  assert.equal(c.strict, false)
  assert.ok(c.ruleIds.includes("git-push-force"))
  assert.deepEqual(c.jev, { enabled: false })

  const j = await effectiveConfig({ GATE_JEV: "1", TYPESAFE_API_KEY: "sekret-123", GATE_JEV_SCOPE: "bash" })
  assert.equal(j.jev.enabled, true)
  assert.equal(j.jev.apiKey, "[set]")
  assert.deepEqual(j.jev.scope, ["bash"])
  assert.equal(j.jev.prompt, "destructive")
  assert.ok(!JSON.stringify(j).includes("sekret-123"))

  assert.match((await effectiveConfig({ GATE_CHECKS: "nope" })).error, /^gate-config: /)
  assert.match((await effectiveConfig({ GATE_JEV: "1" })).jev.error, /TYPESAFE_API_KEY/)
})

test("CLI: text and JSON output, key never printed", () => {
  const env = { ...process.env, GATE_JEV: "1", TYPESAFE_API_KEY: "sekret-123" }
  for (const k of Object.keys(env)) if (/^GATE_/.test(k) && k !== "GATE_JEV") delete env[k]
  const text = spawnSync(process.execPath, [cli, "git push --force"], { env, encoding: "utf8" })
  assert.equal(text.status, 0)
  assert.match(text.stdout, /decision: ask/)
  assert.match(text.stdout, /source: +git-push-force/)
  const json = spawnSync(process.execPath, [cli, "--json", "--mcp", "mcp__db__drop_table", "{}"], { env, encoding: "utf8" })
  assert.equal(JSON.parse(json.stdout).source, "mcp-destructive-tool")
  const conf = spawnSync(process.execPath, [cli], { env, encoding: "utf8" })
  assert.match(conf.stdout, /packs: +base, destructive/)
  assert.match(conf.stdout, /api key \[set\]/)
  for (const out of [text.stdout, json.stdout, conf.stdout]) assert.ok(!out.includes("sekret-123"))
})

test("the skill's documented invocations pass the gate themselves", () => {
  for (const command of [
    `node "/plugin/lib/check.mjs" 'rm -rf build'`,
    `node "/plugin/lib/check.mjs" 'git push --force origin main'`,
    `node "/plugin/lib/check.mjs" --json 'psql -c "DROP TABLE x"'`,
    `node "/plugin/lib/check.mjs" --mcp mcp__db__execute_sql '{"query":"DROP TABLE users"}'`,
    `node "/plugin/lib/check.mjs" --config`,
  ]) {
    const r = spawnSync(process.execPath, [engine], {
      env: { PATH: process.env.PATH, GATE_RUN: "1" },
      input: JSON.stringify({ tool_name: "Bash", tool_input: { command } }),
      encoding: "utf8",
    })
    assert.equal(r.stdout, "", command)
  }
})

test("--cwd resolves scripts the command runs", async () => {
  const dir = mkdtempSync(join(tmpdir(), "check-cwd-"))
  writeFileSync(join(dir, "x.sh"), "terraform apply\n")
  const env = { GATE_CHECKS: "destructive,terraform" }
  const r = await checkCall(bash("bash x.sh"), { env, cwd: dir })
  assert.equal(r.source, "script")
  assert.match(r.reason, /x\.sh runs terraform/)
  const elsewhere = await checkCall(bash("bash x.sh"), { env, cwd: tmpdir() })
  assert.equal(elsewhere.decision, "none")
})

test("checkCall: a relative GATE_RULES_FILE resolves against the git root of --cwd", async () => {
  const root = mkdtempSync(join(tmpdir(), "check-project-"))
  mkdirSync(join(root, ".git"))
  mkdirSync(join(root, ".claude"))
  mkdirSync(join(root, "src"))
  writeFileSync(
    join(root, ".claude", "rules.json"),
    JSON.stringify({ rules: [{ id: "deployctl", kind: "cli-gated", programs: ["deployctl"], gatedPrefixes: [["release"]] }] }),
  )
  const env = { GATE_CHECKS: "none", GATE_RULES_FILE: ".claude/rules.json" }
  const r = await checkCall(bash("deployctl release v1"), { env, cwd: join(root, "src") })
  assert.equal(r.decision, "ask")
  assert.equal(r.source, "deployctl")
})
