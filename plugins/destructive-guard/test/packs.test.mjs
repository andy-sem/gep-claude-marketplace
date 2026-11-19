import { test } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import {
  DEFAULT_PACKS,
  RulesError,
  composeRules,
  loadPacks,
  packPath,
} from "../lib/gate-engine.mjs"

const fixture = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("./fixtures/rules.json", import.meta.url)),
    "utf8",
  ),
)
const byId = (rules) => [...rules].sort((a, b) => a.id.localeCompare(b.id))
const wrapper = fileURLToPath(new URL("../hooks/gate.sh", import.meta.url))

test("ported packs match the matching parts of the test ruleset", () => {
  const composed = composeRules(["base", "postgres", "terraform"].map(packPath))
  for (const key of [
    "wrappers",
    "runners",
    "inertPrograms",
    "inertUnsafeFlags",
  ]) {
    assert.deepEqual(composed[key], fixture[key], key)
  }
  for (const p of composed.scriptPatterns) {
    assert.ok(fixture.scriptPatterns.includes(p), p)
  }
  for (const rule of composed.rules) {
    assert.deepEqual(rule, fixture.rules.find((r) => r.id === rule.id), rule.id)
  }
  assert.deepEqual(byId(composed.rules).map((r) => r.id), [
    "pg_restore",
    "psql",
    "terraform",
  ])
  assert.deepEqual(composed.scriptScanExempt, [])
})

test("every pack loads on its own after base", () => {
  for (const name of ["destructive", "postgres", "terraform"]) {
    assert.doesNotThrow(() => loadPacks([packPath("base"), packPath(name)]), name)
  }
})

test("composeRules rejects duplicate rule ids and bad shapes", () => {
  const dir = mkdtempSync(join(tmpdir(), "gate-packs-"))
  const write = (name, obj) => {
    const p = join(dir, name)
    writeFileSync(p, typeof obj === "string" ? obj : JSON.stringify(obj))
    return p
  }
  const a = write("a.json", {
    rules: [{ id: "x", kind: "cli-gated", programs: ["x"], gatedPrefixes: [[]] }],
  })
  assert.throws(() => composeRules([a, a]), RulesError)
  assert.throws(() => composeRules([write("b.json", "[]")]), RulesError)
  assert.throws(() => composeRules([write("c.json", "{nope")]), RulesError)
  assert.throws(
    () => composeRules([write("d.json", { inertUnsafeFlags: { rg: "x" } })]),
    RulesError,
  )
  assert.throws(() => composeRules([join(dir, "missing.json")]), RulesError)
})

test("composeRules merges string lists without duplicates", () => {
  const dir = mkdtempSync(join(tmpdir(), "gate-packs-"))
  const a = join(dir, "a.json")
  const b = join(dir, "b.json")
  writeFileSync(a, JSON.stringify({ inertPrograms: ["ls", "cat"], inertUnsafeFlags: { rg: ["--pre"] } }))
  writeFileSync(b, JSON.stringify({ inertPrograms: ["cat", "wc"], inertUnsafeFlags: { rg: ["--pre", "-z"] } }))
  const m = composeRules([a, b])
  assert.deepEqual(m.inertPrograms, ["ls", "cat", "wc"])
  assert.deepEqual(m.inertUnsafeFlags, { rg: ["--pre", "-z"] })
})

test("DEFAULT_PACKS is base + destructive", () => {
  assert.deepEqual(DEFAULT_PACKS, ["base", "destructive"])
})

test("without GATE_RULES the hook loads the default packs", () => {
  const run = (command) =>
    spawnSync("bash", [wrapper], {
      input: JSON.stringify({ tool_name: "Bash", tool_input: { command }, cwd: tmpdir() }),
      encoding: "utf8",
      env: { ...process.env, GATE_RULES: "", GATE_JEV: "", GATE_INFRA_NODE: process.execPath },
    })
  const asked = JSON.parse(run("terraform destroy").stdout).hookSpecificOutput
  assert.equal(asked.permissionDecision, "ask")
  assert.match(asked.permissionDecisionReason, /^terraform-destroy:/)
  assert.match(
    JSON.parse(run("git push --force").stdout).hookSpecificOutput
      .permissionDecisionReason,
    /^git-push-force:/,
  )
  assert.equal(run("git push").stdout, "")
  assert.equal(run("git status").stdout, "")
  assert.equal(run("ls -la").stdout, "")
})
