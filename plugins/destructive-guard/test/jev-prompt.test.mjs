import { test } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import {
  DEFAULT_PROMPT,
  JevConfigError,
  askJev,
  builtinPrompt,
  jevDecision,
  promptFromEnv,
  readJevConfig,
  validatePrompt,
} from "../lib/gate-jev.mjs"

const baseEnv = { GATE_JEV: "1", TYPESAFE_API_KEY: "key-123" }
const jevDir = fileURLToPath(new URL("../jev/", import.meta.url))
const cfgWith = (prompt) => ({
  apiKey: "k",
  url: "https://example.test/v1",
  model: "m",
  timeoutMs: 500,
  allowThreshold: 0.95,
  escalateThreshold: 0.5,
  prompt,
})
const d = (read_only, reversible_change, destructive) => ({
  read_only,
  reversible_change,
  destructive,
})

test("the default prompt is destructive and covers local and remote calls", () => {
  assert.equal(DEFAULT_PROMPT, "destructive")
  const p = readJevConfig(baseEnv).prompt
  assert.equal(p.question, "destructive")
  assert.deepEqual(Object.keys(p.criteria), ["read_only", "reversible_change", "destructive"])
  assert.deepEqual(p.ask, ["destructive"])
  assert.deepEqual(p.safe, ["read_only", "reversible_change"])
  assert.match(p.instructions, /local machine/)
  const destructive = p.criteria.destructive.examples.join("\n")
  for (const needle of [
    "rm -rf",
    "git reset --hard",
    "git clean -fdx",
    "git stash drop",
    "git push --force",
    "docker volume rm",
    "terraform destroy",
    "DROP TABLE",
    "an MCP tool call that deletes",
    "a script that runs",
  ]) {
    assert.ok(destructive.includes(needle), needle)
  }
})

test("built-in prompts are valid and name no specific MCP server or product", () => {
  for (const f of readdirSync(jevDir).filter((f) => f.endsWith(".json"))) {
    const text = readFileSync(join(jevDir, f), "utf8")
    assert.doesNotThrow(() => validatePrompt(JSON.parse(text), f))
    assert.doesNotMatch(text, /mcp__\w/, f)
    assert.doesNotMatch(text, /jira|atlassian|chrome|cloudflare|wrangler|supabase|gcloud|google/i, f)
  }
})

test("jevDecision with the destructive prompt", () => {
  const cfg = cfgWith(builtinPrompt("destructive"))
  assert.deepEqual(jevDecision(d(0.1, 0.2, 0.7), cfg), {
    decision: "ask",
    reason: "jev: destructive p=0.70 risk=0.70",
  })
  assert.deepEqual(jevDecision(d(0.02, 0.96, 0.02), cfg), {
    decision: "pass",
    reason: "jev: reversible_change p=0.96 safe=0.98",
  })
  assert.equal(jevDecision(d(0.3, 0.3, 0.4), cfg), null)
})

test("askJev sends the destructive question and parses its answer", async () => {
  let body
  const fetchImpl = async (_url, init) => {
    body = JSON.parse(init.body)
    return {
      ok: true,
      status: 200,
      json: async () => ({
        answers: { destructive: { type: "choice", probabilities: d(0.05, 0.05, 0.9) } },
      }),
    }
  }
  const out = await askJev(
    { tool: "Bash", command: "rm -rf ~/work", scripts: [], notes: [] },
    cfgWith(builtinPrompt("destructive")),
    { fetchImpl },
  )
  assert.deepEqual(Object.keys(body.questions), ["destructive"])
  assert.equal(body.state.context.policy, builtinPrompt("destructive").context.policy)
  assert.deepEqual(out.probabilities, d(0.05, 0.05, 0.9))
})

test("GATE_JEV_PROMPT selects a built-in or a file", () => {
  assert.equal(promptFromEnv({ GATE_JEV_PROMPT: "cloud-change" }).question, "cloud_change")
  assert.equal(promptFromEnv({ GATE_JEV_PROMPT: " " }).question, "destructive")
  const dir = mkdtempSync(join(tmpdir(), "jev-prompt-"))
  const custom = {
    question: "risky",
    instructions: "Is this risky?",
    context: { environment: "e" },
    criteria: {
      fine: { description: "fine", examples: ["ls"] },
      risky: { description: "risky", examples: ["rm -rf /"] },
    },
    ask: ["risky"],
    safe: ["fine"],
  }
  const path = join(dir, "p.json")
  writeFileSync(path, JSON.stringify(custom))
  assert.deepEqual(promptFromEnv({ GATE_JEV_PROMPT: path }), custom)
})

test("a relative GATE_JEV_PROMPT or GATE_JEV_LOG resolves against CLAUDE_PROJECT_DIR", () => {
  const root = mkdtempSync(join(tmpdir(), "jev-project-"))
  const custom = {
    question: "risky",
    instructions: "Is this risky?",
    context: { environment: "e" },
    criteria: {
      fine: { description: "fine", examples: ["ls"] },
      risky: { description: "risky", examples: ["rm -rf /"] },
    },
    ask: ["risky"],
    safe: ["fine"],
  }
  writeFileSync(join(root, "prompt.json"), JSON.stringify(custom))
  const env = { ...baseEnv, CLAUDE_PROJECT_DIR: root, GATE_JEV_PROMPT: "./prompt.json", GATE_JEV_LOG: "jev.jsonl" }
  const cfg = readJevConfig(env)
  assert.deepEqual(cfg.prompt, custom)
  assert.equal(cfg.logPath, join(root, "jev.jsonl"))
  assert.equal(readJevConfig({ ...baseEnv, GATE_JEV_LOG: "/abs/j.jsonl" }).logPath, "/abs/j.jsonl")
})

test("GATE_JEV_INSTRUCTIONS, GATE_JEV_CONTEXT and GATE_JEV_POLICY override the prompt", () => {
  const p = promptFromEnv({
    GATE_JEV_INSTRUCTIONS: "Could this lose data?",
    GATE_JEV_CONTEXT: "A monorepo; data/ holds fixtures that cannot be regenerated.",
    GATE_JEV_POLICY: "Ask before anything that deletes files in data/.",
  })
  assert.equal(p.instructions, "Could this lose data?")
  assert.equal(p.context.project, "A monorepo; data/ holds fixtures that cannot be regenerated.")
  assert.equal(p.context.policy, "Ask before anything that deletes files in data/.")
  assert.equal(p.context.environment, builtinPrompt("destructive").context.environment)
  // the built-in is not mutated
  assert.notEqual(builtinPrompt("destructive").instructions, "Could this lose data?")
})

test("bad prompt settings fail with JevConfigError (the gate then asks)", () => {
  const dir = mkdtempSync(join(tmpdir(), "jev-prompt-bad-"))
  const write = (name, obj) => {
    const p = join(dir, name)
    writeFileSync(p, typeof obj === "string" ? obj : JSON.stringify(obj))
    return p
  }
  const good = builtinPrompt("destructive")
  for (const value of [
    "nope",
    "../lib/x",
    join(dir, "missing.json"),
    write("syntax.json", "{"),
    write("overlap.json", { ...good, safe: ["read_only", "destructive"] }),
    write("unknown.json", { ...good, ask: ["catastrophic"] }),
    write("one.json", { ...good, criteria: { a: good.criteria.read_only }, ask: ["a"], safe: ["a"] }),
    write("q.json", { ...good, question: "Bad Id" }),
    write("ctx.json", { ...good, context: { a: 1 } }),
    write("ex.json", { ...good, criteria: { ...good.criteria, destructive: { description: "x" } } }),
  ]) {
    assert.throws(
      () => readJevConfig({ ...baseEnv, GATE_JEV_PROMPT: value }),
      JevConfigError,
      value,
    )
  }
})
