import { test } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, readFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import {
  JEV_URL,
  JevConfigError,
  askJev,
  jevDecision,
  buildState,
  parseAnswer,
  readJevConfig,
  redact,
  redactMcpInput,
  redactScript,
  runJev,
} from "../lib/gate-jev.mjs"

const baseEnv = { GATE_JEV: "1", TYPESAFE_API_KEY: "key-123" }
const cfg = {
  apiKey: "key-123",
  url: "https://example.test/v1",
  model: "jev-latest",
  timeoutMs: 500,
  allowThreshold: 0.95,
  escalateThreshold: 0.5,
  logPath: undefined,
}

const probs = (unrelated, read_only, cloud_or_data_change, destructive) => ({
  unrelated,
  read_only,
  cloud_or_data_change,
  destructive,
})
const answer = (p) => ({
  answers: { cloud_change: { type: "choice", probabilities: p } },
})
const okResponse = (p, usage) => ({
  status: 200,
  ok: true,
  headers: { get: () => null },
  json: async () => ({ ...answer(p), ...(usage ? { usage } : {}) }),
})
const bashCall = (command, scripts = []) => ({ tool: "Bash", command, scripts })
const mcpCall = (tool, input = {}) => ({ tool, input })
const statusResponse = (status, retryAfter = null) => ({
  status,
  ok: false,
  headers: { get: (name) => (name === "retry-after" ? retryAfter : null) },
  json: async () => ({}),
})

// ---------------------------------------------------------------------------
// redact
// ---------------------------------------------------------------------------

test("redact returns null for commands referencing .env files", () => {
  assert.equal(redact("cat .env"), null)
  assert.equal(redact("cat apps/x/.env.local"), null)
  assert.equal(redact("source .envrc"), null)
})

test("redact strips URL credentials", () => {
  assert.equal(
    redact("git clone https://u:p@host/repo.git"),
    "git clone https://[REDACTED]@host/repo.git",
  )
})

test("redact strips Bearer, Basic and Token values", () => {
  for (const scheme of ["Bearer", "Basic", "Token"]) {
    const out = redact(`curl -H 'Authorization: ${scheme} sekret123' x`)
    assert.ok(!out.includes("sekret123"), out)
    assert.ok(out.includes("[REDACTED]"), out)
  }
  assert.equal(redact("echo Bearer abc123"), "echo Bearer [REDACTED]")
})

test("redact strips secret-named NAME=value and NAME: value", () => {
  assert.equal(redact("run api_key=abc"), "run api_key=[REDACTED]")
  assert.equal(redact('password: "x y"'), "password: [REDACTED]")
  assert.equal(redact("x --db-secret=hunter2"), "x --db-secret=[REDACTED]")
})

test("redact strips --password style flag values", () => {
  const out = redact("mysql --password hunter2 -u root")
  assert.ok(!out.includes("hunter2"), out)
  assert.equal(out, "mysql --password [REDACTED] -u root")
})

test("redact strips environment assignments", () => {
  assert.equal(redact("FOO=bar cmd"), "FOO=[REDACTED] cmd")
  assert.equal(redact("export FOO=bar"), "export FOO=[REDACTED]")
})

test("redact strips long hex runs", () => {
  const hex = "0123456789abcdef0123456789abcdef"
  assert.equal(redact(`echo ${hex}`), "echo [REDACTED]")
  const short = "0123456789abcdef"
  assert.equal(redact(`echo ${short}`), `echo ${short}`)
})

test("redact strips long mixed-case base64 runs", () => {
  const run = "AbCdEf0123456789AbCdEf0123456789xyz"
  assert.equal(redact(`echo ${run}`), "echo [REDACTED]")
})

test("redact leaves ordinary commands unchanged", () => {
  for (const cmd of [
    "git status",
    "ls -la src",
    "cat src/lib/components/some/very/long/path/to/a/file/name-here.ts",
  ])
    assert.equal(redact(cmd), cmd)
})

// ---------------------------------------------------------------------------
// readJevConfig
// ---------------------------------------------------------------------------

test("readJevConfig returns null when GATE_JEV is off", () => {
  assert.equal(readJevConfig({}), null)
  assert.equal(readJevConfig({ GATE_JEV: "" }), null)
  assert.equal(readJevConfig({ GATE_JEV: "0" }), null)
})

test("readJevConfig applies defaults", () => {
  const c = readJevConfig(baseEnv)
  assert.deepEqual(c, {
    apiKey: "key-123",
    url: JEV_URL,
    model: "jev-latest",
    allowThreshold: 0.95,
    escalateThreshold: 0.5,
    timeoutMs: 1500,
    logPath: undefined,
  })
})

test("readJevConfig treats empty optional vars as unset", () => {
  const c = readJevConfig({
    ...baseEnv,
    GATE_JEV_URL: "  ",
    GATE_JEV_MODEL: "",
    GATE_JEV_TIMEOUT_MS: "",
    GATE_JEV_ALLOW_THRESHOLD: "",
    GATE_JEV_ESCALATE_THRESHOLD: "",
    GATE_JEV_LOG: "",
  })
  assert.equal(c.url, JEV_URL)
  assert.equal(c.model, "jev-latest")
  assert.equal(c.timeoutMs, 1500)
  assert.equal(c.allowThreshold, 0.95)
  assert.equal(c.escalateThreshold, 0.5)
  assert.equal(c.logPath, undefined)
})

test("readJevConfig reads overrides", () => {
  const c = readJevConfig({
    ...baseEnv,
    GATE_JEV_MODEL: "m",
    GATE_JEV_TIMEOUT_MS: "30000",
    GATE_JEV_ALLOW_THRESHOLD: "0.9",
    GATE_JEV_ESCALATE_THRESHOLD: "1",
    GATE_JEV_LOG: "/tmp/x.jsonl",
  })
  assert.equal(c.model, "m")
  assert.equal(c.timeoutMs, 30000)
  assert.equal(c.allowThreshold, 0.9)
  assert.equal(c.escalateThreshold, 1)
  assert.equal(c.logPath, "/tmp/x.jsonl")
})

test("readJevConfig throws JevConfigError on invalid input", () => {
  const bad = [
    { GATE_JEV: "yes", TYPESAFE_API_KEY: "k" },
    { GATE_JEV: "1" },
    { ...baseEnv, GATE_JEV_ALLOW_THRESHOLD: "1.5" },
    { ...baseEnv, GATE_JEV_ALLOW_THRESHOLD: "-0.1" },
    { ...baseEnv, GATE_JEV_ALLOW_THRESHOLD: "abc" },
    { ...baseEnv, GATE_JEV_ESCALATE_THRESHOLD: "2" },
    { ...baseEnv, GATE_JEV_ESCALATE_THRESHOLD: "abc" },
    { ...baseEnv, GATE_JEV_TIMEOUT_MS: "0" },
    { ...baseEnv, GATE_JEV_TIMEOUT_MS: "30001" },
    { ...baseEnv, GATE_JEV_TIMEOUT_MS: "1.5" },
    { ...baseEnv, GATE_JEV_TIMEOUT_MS: "abc" },
    { ...baseEnv, GATE_JEV_URL: "not a url" },
    { ...baseEnv, GATE_JEV_URL: "http://example.com" },
  ]
  for (const env of bad)
    assert.throws(() => readJevConfig(env), JevConfigError, JSON.stringify(env))
})

test("readJevConfig accepts loopback http URLs", () => {
  assert.equal(
    readJevConfig({ ...baseEnv, GATE_JEV_URL: "http://127.0.0.1:1234" }).url,
    "http://127.0.0.1:1234",
  )
  assert.equal(
    readJevConfig({ ...baseEnv, GATE_JEV_URL: "http://localhost" }).url,
    "http://localhost",
  )
})

// ---------------------------------------------------------------------------
// jevDecision
// ---------------------------------------------------------------------------

test("jevDecision passes confident read_only and unrelated", () => {
  assert.deepEqual(jevDecision(probs(0.01, 0.97, 0.01, 0.01), cfg), {
    decision: "pass",
    reason: "jev: read_only p=0.97 safe=0.98",
  })
  assert.deepEqual(jevDecision(probs(0.97, 0.01, 0.01, 0.01), cfg), {
    decision: "pass",
    reason: "jev: unrelated p=0.97 safe=0.98",
  })
})

test("jevDecision sums unrelated and read_only for the safe side", () => {
  assert.deepEqual(jevDecision(probs(0.6, 0.36, 0.02, 0.02), cfg), {
    decision: "pass",
    reason: "jev: unrelated p=0.60 safe=0.96",
  })
})

test("jevDecision returns null when the safe side is below the threshold", () => {
  assert.equal(jevDecision(probs(0.04, 0.9, 0.04, 0.02), cfg), null)
  assert.equal(jevDecision(probs(0.4, 0.5, 0.05, 0.05), cfg), null)
})

test("jevDecision asks when risk exceeds the escalate threshold", () => {
  const d = jevDecision(probs(0.1, 0.35, 0.25, 0.3), cfg)
  assert.equal(d.decision, "ask")
  assert.match(d.reason, /^jev: destructive p=0\.30 risk=0\.55$/)
})

test("jevDecision does not ask at exactly the escalate threshold", () => {
  assert.equal(jevDecision(probs(0.25, 0.25, 0.25, 0.25), cfg), null)
})

test("jevDecision names cloud_or_data_change when it is larger", () => {
  const d = jevDecision(probs(0.05, 0.05, 0.6, 0.3), cfg)
  assert.equal(d.decision, "ask")
  assert.match(d.reason, /^jev: cloud_or_data_change p=0\.60 risk=0\.90$/)
})

// ---------------------------------------------------------------------------
// parseAnswer
// ---------------------------------------------------------------------------

test("parseAnswer accepts a well-formed answer", () => {
  const p = probs(0.7, 0.1, 0.1, 0.1)
  assert.deepEqual(parseAnswer(answer(p)), p)
})

test("parseAnswer returns null for malformed shapes", () => {
  const good = probs(0.7, 0.1, 0.1, 0.1)
  assert.equal(parseAnswer(null), null)
  assert.equal(parseAnswer({}), null)
  assert.equal(
    parseAnswer({
      answers: { cloud_change: { type: "text", probabilities: good } },
    }),
    null,
  )
  assert.equal(
    parseAnswer({
      answers: { cloud_change: { type: "choice", probabilities: "x" } },
    }),
    null,
  )
  assert.equal(parseAnswer(answer({ ...good, destructive: undefined })), null)
  assert.equal(parseAnswer(answer({ ...good, destructive: "0.1" })), null)
  assert.equal(parseAnswer(answer(probs(1.2, -0.1, 0, -0.1))), null)
  assert.equal(parseAnswer(answer(probs(0.5, 0.1, 0.1, 0.1))), null)
})

// ---------------------------------------------------------------------------
// askJev
// ---------------------------------------------------------------------------

test("askJev returns probabilities, usage and latency and sends a well-formed request", async () => {
  const p = probs(0.01, 0.97, 0.01, 0.01)
  const calls = []
  const fetchImpl = async (url, init) => {
    calls.push({ url, init })
    return okResponse(p, { input_tokens: 900, output_tokens: 12 })
  }
  const out = await askJev({ tool: "Bash", command: "git status" }, cfg, {
    fetchImpl,
  })
  assert.deepEqual(out.probabilities, p)
  assert.deepEqual(out.usage, { input_tokens: 900, output_tokens: 12 })
  assert.equal(typeof out.latencyMs, "number")
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, cfg.url)
  assert.equal(calls[0].init.method, "POST")
  assert.equal(calls[0].init.headers.authorization, "Bearer key-123")
  const body = JSON.parse(calls[0].init.body)
  assert.equal(body.model, "jev-latest")
  assert.equal(body.state.tool, "Bash")
  assert.equal(body.state.command, "git status")
  assert.deepEqual(Object.keys(body.state.context).sort(), [
    "environment",
    "inputs",
    "policy",
    "projects",
  ])
  assert.deepEqual(Object.keys(body.questions), ["cloud_change"])
  const q = body.questions.cloud_change
  assert.equal(q.type, "choice")
  assert.equal(
    q.instructions,
    "Does this call change cloud services, remote infrastructure or databases?",
  )
  assert.deepEqual(Object.keys(q.criteria), [
    "unrelated",
    "read_only",
    "cloud_or_data_change",
    "destructive",
  ])
  for (const option of Object.values(q.criteria)) {
    assert.equal(typeof option.description, "string")
    assert.ok(option.examples.length > 0)
  }
  // examples cover Bash, scripts, Terraform, workflows, database and cloud MCP, and
  // unrelated calls
  const examples = Object.values(q.criteria)
    .flatMap((o) => o.examples)
    .join("\n")
  for (const needle of [
    "kubectl apply",
    "bash infra/apply.sh",
    "node scripts/provision-dev.mjs",
    "terraform plan",
    "terraform apply",
    "terraform destroy",
    "terraform test, where every test file",
    "terraform test, where a test file",
    "gh workflow run",
    "execute_sql with SELECT",
    "execute_sql with INSERT",
    "execute_sql with DROP",
    "apply_migration",
    "mcp__cloud__run_command",
    "git push --force",
    "wrangler dev",
    "editJiraIssue",
    "computer with a click",
  ]) {
    assert.ok(examples.includes(needle), needle)
  }
  assert.ok(!JSON.stringify(body).includes(["local", "write"].join("_")))
})

test("askJev has a latency on errors too", async () => {
  const out = await askJev({ tool: "Bash", command: "ls" }, cfg, {
    fetchImpl: async () => statusResponse(500),
  })
  assert.equal(out.error, "http 500")
  assert.equal(typeof out.latencyMs, "number")
})

test("askJev reports usage null when Jev sends none", async () => {
  const out = await askJev({ tool: "Bash", command: "ls" }, cfg, {
    fetchImpl: async () => okResponse(probs(0.01, 0.97, 0.01, 0.01)),
  })
  assert.equal(out.usage, null)
})

test("askJev reports non-retryable http errors", async () => {
  const out = await askJev({ tool: "Bash", command: "ls" }, cfg, {
    fetchImpl: async () => statusResponse(401),
  })
  assert.equal(out.error, "http 401")
})

test("askJev retries 429 and then succeeds", async () => {
  const p = probs(0.97, 0.01, 0.01, 0.01)
  let n = 0
  const fetchImpl = async () =>
    ++n === 1 ? statusResponse(429, "0") : okResponse(p)
  const out = await askJev({ tool: "Bash", command: "ls" }, cfg, { fetchImpl })
  assert.deepEqual(out.probabilities, p)
  assert.equal(n, 2)
})

test("askJev gives up when retry-after exceeds the budget", async () => {
  let n = 0
  const fetchImpl = async () => (n++, statusResponse(529, "10"))
  const out = await askJev(
    { tool: "Bash", command: "ls" },
    { ...cfg, timeoutMs: 200 },
    { fetchImpl },
  )
  assert.equal(out.error, "http 529")
  assert.equal(n, 1)
})

test("askJev times out when fetch hangs until aborted", async () => {
  const fetchImpl = (url, { signal }) =>
    new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("aborted")))
    })
  const out = await askJev(
    { tool: "Bash", command: "ls" },
    { ...cfg, timeoutMs: 20 },
    { fetchImpl },
  )
  assert.equal(out.error, "timeout")
})

test("askJev reports network failures", async () => {
  const fetchImpl = async () => {
    throw new Error("boom")
  }
  assert.equal(
    (await askJev({ tool: "Bash", command: "ls" }, cfg, { fetchImpl })).error,
    "network",
  )
})

test("askJev reports malformed bodies", async () => {
  const throwing = async () => ({
    status: 200,
    ok: true,
    headers: { get: () => null },
    json: async () => {
      throw new Error("bad json")
    },
  })
  assert.equal(
    (
      await askJev({ tool: "Bash", command: "ls" }, cfg, {
        fetchImpl: throwing,
      })
    ).error,
    "malformed",
  )
  const wrongShape = async () => ({
    status: 200,
    ok: true,
    headers: { get: () => null },
    json: async () => ({ answers: {} }),
  })
  assert.equal(
    (
      await askJev({ tool: "Bash", command: "ls" }, cfg, {
        fetchImpl: wrongShape,
      })
    ).error,
    "malformed",
  )
})

// ---------------------------------------------------------------------------
// runJev
// ---------------------------------------------------------------------------

test("runJev returns the rule result unchanged when Jev fails", async () => {
  const rule = { decision: "ask", reason: "rule: x" }
  const fetchImpl = async () => statusResponse(500)
  assert.equal(await runJev(bashCall("ls"), rule, cfg, { fetchImpl }), rule)
  assert.equal(await runJev(bashCall("ls"), null, cfg, { fetchImpl }), null)
  assert.equal(
    await runJev(mcpCall("mcp__x__y"), rule, cfg, { fetchImpl }),
    rule,
  )
  assert.equal(
    await runJev(mcpCall("mcp__x__y"), null, cfg, { fetchImpl }),
    null,
  )
})

test("runJev falls back to the rule result for every failure mode", async () => {
  const rule = { decision: "ask", reason: "rule: x" }
  const hang = (url, { signal }) =>
    new Promise((resolve, reject) =>
      signal.addEventListener("abort", () => reject(new Error("aborted"))),
    )
  const malformed = async () => ({
    status: 200,
    ok: true,
    headers: { get: () => null },
    json: async () => ({ answers: {} }),
  })
  const modes = {
    timeout: hang,
    429: async () => statusResponse(429, "10"),
    529: async () => statusResponse(529, "10"),
    401: async () => statusResponse(401),
    malformed,
    network: async () => {
      throw new Error("down")
    },
  }
  for (const [mode, fetchImpl] of Object.entries(modes)) {
    const slow = { ...cfg, timeoutMs: 60 }
    for (const call of [bashCall("ls"), mcpCall("mcp__x__y", { a: 1 })]) {
      assert.equal(await runJev(call, rule, slow, { fetchImpl }), rule, mode)
      assert.equal(await runJev(call, null, slow, { fetchImpl }), null, mode)
    }
  }
})

test("runJev never sends Bash commands that reference .env", async () => {
  const rule = { decision: "ask", reason: "rule: env" }
  let called = false
  const out = await runJev(bashCall("cat .env"), rule, cfg, {
    fetchImpl: async () => {
      called = true
      return okResponse(probs(0, 1, 0, 0))
    },
  })
  assert.equal(out, rule)
  assert.equal(called, false)
})

test("runJev lifts a rule ask when Jev passes, for Bash and MCP", async () => {
  const fetchImpl = async () => okResponse(probs(0.01, 0.98, 0.005, 0.005))
  const rule = { decision: "ask", reason: "rule: x" }
  assert.equal(await runJev(bashCall("ls"), rule, cfg, { fetchImpl }), null)
  assert.equal(
    await runJev(mcpCall("mcp__x__y"), rule, cfg, { fetchImpl }),
    null,
  )
})

test("runJev asks even when the rules had no opinion", async () => {
  const fetchImpl = async () => okResponse(probs(0, 0.05, 0.05, 0.9))
  for (const call of [bashCall("rm -rf x"), mcpCall("mcp__x__y")]) {
    const out = await runJev(call, null, cfg, { fetchImpl })
    assert.equal(out.decision, "ask")
    assert.match(out.reason, /^jev: destructive p=0\.90 risk=0\.95$/)
  }
})

test("runJev keeps the rule result when Jev is undecided", async () => {
  const rule = { decision: "ask", reason: "rule: x" }
  const out = await runJev(bashCall("ls"), rule, cfg, {
    fetchImpl: async () => okResponse(probs(0.04, 0.9, 0.04, 0.02)),
  })
  assert.equal(out, rule)
})

test("runJev sends the Bash payload with scripts and notes", async () => {
  let body
  await runJev(
    bashCall("bash infra/cloud/apply.sh --apply", [
      {
        path: "infra/cloud/apply.sh",
        content: "terraform apply\nTOKEN=abcdef\n",
      },
      { path: "lib/.env.sh", content: "ok\ncat .env\nfoo\n" },
    ]),
    null,
    cfg,
    {
      fetchImpl: async (url, init) => {
        body = JSON.parse(init.body)
        return okResponse(probs(0.01, 0.97, 0.01, 0.01))
      },
    },
  )
  assert.equal(body.state.tool, "Bash")
  assert.equal(body.state.command, "bash infra/cloud/apply.sh --apply")
  assert.deepEqual(body.state.scripts, [
    {
      path: "infra/cloud/apply.sh",
      content: "terraform apply\nTOKEN=[REDACTED]\n",
    },
    {
      path: "lib/.env.sh",
      content: `ok\n[line removed: .env reference]\nfoo\n`,
    },
  ])
  assert.deepEqual(body.state.notes, [])
})

test("buildState caps the command and notes the cut", () => {
  const state = buildState(bashCall(`echo ${"a ".repeat(6000)}`))
  assert.equal(state.command.length, 8000)
  assert.deepEqual(state.notes, [
    `command cut to 8000 of ${`echo ${"a ".repeat(6000)}`.length} characters`,
  ])
})

test("buildState caps scripts at 64 KB in total and notes it", () => {
  const big = (n) => ({ path: `f${n}.mjs`, content: "x".repeat(40000) })
  const state = buildState(
    bashCall("node f1.mjs", [
      big(1),
      big(2),
      { ...big(3), content: "y" },
      { path: "cut.mjs", content: "z", truncated: true, size: 70000 },
    ]),
  )
  assert.deepEqual(
    state.scripts.map((s) => s.path),
    ["f1.mjs", "f2.mjs"],
  )
  assert.equal(
    state.scripts.reduce((n, s) => n + Buffer.byteLength(s.content), 0),
    65536,
  )
  assert.deepEqual(state.notes, [
    "cut.mjs cut at 64 KB",
    "scripts cut at 64 KB total: f2.mjs truncated; omitted: f3.mjs, cut.mjs",
  ])
})

test("buildState notes a file cut at the per-file cap", () => {
  const state = buildState(
    bashCall("node a.mjs", [
      { path: "a.mjs", content: "x", truncated: true, size: 70000 },
    ]),
  )
  assert.deepEqual(state.notes, ["a.mjs cut at 64 KB"])
  assert.equal(state.scripts.length, 1)
})

test("runJev sends the MCP payload with a cut note", async () => {
  let body
  const fetchImpl = async (url, init) => {
    body = JSON.parse(init.body)
    return okResponse(probs(0.01, 0.97, 0.01, 0.01))
  }
  await runJev(
    mcpCall("mcp__plugin_dbhost_dbhost__execute_sql", {
      query: "SELECT 1",
    }),
    null,
    cfg,
    { fetchImpl },
  )
  assert.equal(body.state.tool, "mcp__plugin_dbhost_dbhost__execute_sql")
  assert.equal(body.state.input, '{"query":"SELECT 1"}')
  assert.deepEqual(body.state.notes, [])
  assert.equal(body.state.command, undefined)

  await runJev(
    mcpCall("mcp__x__y", { text: "lorem ipsum ".repeat(750) }),
    null,
    cfg,
    {
      fetchImpl,
    },
  )
  assert.equal(body.state.input.length, 8000)
  const full = JSON.stringify({ text: "lorem ipsum ".repeat(750) }).length
  assert.deepEqual(body.state.notes, [
    `input cut to 8000 of ${full} characters`,
  ])
})

// ---------------------------------------------------------------------------
// redactScript / redactMcpInput
// ---------------------------------------------------------------------------

test("redactScript removes .env lines, redacts secrets and keeps the call", () => {
  const out = redactScript(
    [
      "#!/bin/bash",
      "source .env.local",
      "export API_TOKEN=abc123",
      'curl -H "Authorization: Bearer sekret" https://x',
      "echo ok",
    ].join("\n"),
  )
  assert.equal(
    out,
    [
      "#!/bin/bash",
      "[line removed: .env reference]",
      "export API_TOKEN=[REDACTED]",
      'curl -H "Authorization: [REDACTED] [REDACTED]" https://x',
      "echo ok",
    ].join("\n"),
  )
  assert.ok(!out.includes("sekret"))
  // JS: process.env is not an .env file
  assert.equal(
    redactScript("const a = process.env.FOO"),
    "const a = process.env.FOO",
  )
})

test("redactMcpInput redacts SQL literals but keeps the statement and plain ids", () => {
  const out = JSON.parse(
    redactMcpInput({
      project_id: "abcdefghijklmnopqrst",
      query:
        "INSERT INTO t (a, b) VALUES ('it''s secret', 5); UPDATE t SET x = 1 WHERE id=5",
    }),
  )
  assert.equal(out.project_id, "abcdefghijklmnopqrst")
  assert.equal(
    out.query,
    "INSERT INTO t (a, b) VALUES ('[REDACTED]', 5); UPDATE t SET x = 1 WHERE id=5",
  )
})

test("redactMcpInput replaces dollar-quoted bodies", () => {
  const out = JSON.parse(
    redactMcpInput({
      sql: "CREATE FUNCTION f() RETURNS text AS $body$ select 'hunter2' $body$; SELECT $$x$$",
    }),
  )
  assert.equal(
    out.sql,
    "CREATE FUNCTION f() RETURNS text AS $body$[REDACTED]$body$; SELECT $$[REDACTED]$$",
  )
})

test("redactMcpInput redacts secret keys, Bearer values and .env mentions in nested JSON", () => {
  const raw = redactMcpInput({
    access_token: "tok-123",
    nested: {
      headers: ["Authorization: Bearer abc.def", "X-Other: fine"],
      note: "line one\nsee .env.local for it\nline three",
      api_key: { deep: "value" },
    },
    count: 3,
  })
  const out = JSON.parse(raw)
  assert.equal(out.access_token, "[REDACTED]")
  assert.equal(out.nested.api_key, "[REDACTED]")
  assert.deepEqual(out.nested.headers, [
    "Authorization: [REDACTED] [REDACTED]",
    "X-Other: fine",
  ])
  assert.equal(
    out.nested.note,
    "line one\n[line removed: .env reference]\nline three",
  )
  assert.equal(out.count, 3)
  for (const secret of ["tok-123", "abc.def", "value"])
    assert.ok(!raw.includes(secret), secret)
})

test("redactMcpInput handles an empty input", () => {
  assert.equal(redactMcpInput(undefined), "{}")
  assert.equal(redactMcpInput({}), "{}")
})

// ---------------------------------------------------------------------------
// audit log
// ---------------------------------------------------------------------------

test("runJev writes a redacted JSONL audit log with tool, usage and latency", async () => {
  const dir = mkdtempSync(join(tmpdir(), "gate-jev-"))
  const logPath = join(dir, "audit.jsonl")
  const logCfg = { ...cfg, logPath }
  const fetchImpl = async () =>
    okResponse(probs(0.01, 0.98, 0.005, 0.005), { input_tokens: 1000 })
  await runJev(
    bashCall("TOPSECRET_X=supersecret123 node a.mjs", [
      { path: "a.mjs", content: "x" },
    ]),
    null,
    logCfg,
    { fetchImpl },
  )
  await runJev(bashCall("cat .env"), null, logCfg, { fetchImpl })
  await runJev(
    mcpCall("mcp__x__y", { password: "supersecret123", q: 1 }),
    { decision: "ask", reason: "x-mcp: y" },
    logCfg,
    { fetchImpl },
  )
  await runJev(bashCall("ls"), { decision: "ask", reason: "r: x" }, logCfg, {
    fetchImpl: async () => statusResponse(401),
  })
  const text = readFileSync(logPath, "utf8")
  assert.ok(!text.includes("supersecret123"), text)
  const lines = text
    .trim()
    .split("\n")
    .map((l) => JSON.parse(l))
  assert.equal(lines.length, 4)
  assert.equal(lines[0].tool, "Bash")
  assert.equal(lines[0].command, "TOPSECRET_X=[REDACTED] node a.mjs")
  assert.deepEqual(lines[0].scripts, ["a.mjs"])
  assert.equal(lines[0].decision, "pass")
  assert.equal(lines[0].rule, null)
  assert.deepEqual(lines[0].usage, { input_tokens: 1000 })
  assert.equal(typeof lines[0].latencyMs, "number")
  assert.equal(lines[0].probabilities.read_only, 0.98)
  assert.ok(lines[0].ts)
  assert.equal(lines[1].command, null)
  assert.match(lines[1].outcome, /^skipped/)
  assert.equal(typeof lines[1].latencyMs, "number")
  assert.equal(lines[2].tool, "mcp__x__y")
  assert.equal(lines[2].input, '{"password":"[REDACTED]","q":1}')
  assert.equal(lines[2].rule, "x-mcp: y")
  assert.equal(lines[2].decision, "pass")
  assert.equal(lines[3].outcome, "fallback: http 401")
  assert.equal(lines[3].rule, "r: x")
  assert.equal(typeof lines[3].latencyMs, "number")
})
