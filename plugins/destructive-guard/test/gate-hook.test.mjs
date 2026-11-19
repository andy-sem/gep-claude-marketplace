import { test, before, after } from "node:test"
import assert from "node:assert/strict"
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { join, dirname } from "node:path"
import { spawn, spawnSync } from "node:child_process"
import { createServer } from "node:http"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = join(here, "..", "..")
const shippedRules = join(here, "fixtures", "rules.json")
const wrapper = join(here, "..", "hooks", "gate.sh")
const dir = mkdtempSync(join(tmpdir(), "gate-hook-"))
const rulesPath = join(dir, "rules.json")
const badRulesPath = join(dir, "bad.json")

before(() => {
  writeFileSync(
    rulesPath,
    JSON.stringify({
      wrappers: [],
      runners: [],
      inertPrograms: ["grep"],
      rules: [
        {
          id: "tf",
          kind: "cli-gated",
          programs: ["terraform"],
          gatedPrefixes: [["apply"]],
        },
      ],
    }),
  )
  writeFileSync(badRulesPath, "{not json")
})

function run(stdin, env = {}) {
  const r = spawnSync("bash", [wrapper], {
    input: stdin,
    encoding: "utf8",
    env: {
      ...process.env,
      GATE_RULES: rulesPath,
      GATE_INFRA_NODE: process.execPath,
      CLAUDE_PROJECT_DIR: repoRoot,
      GATE_JEV: "",
      GATE_JEV_LOG: "",
      ...env,
    },
  })
  return { status: r.status, stdout: r.stdout }
}

const bash = (command, cwd = here) =>
  JSON.stringify({ tool_name: "Bash", tool_input: { command }, cwd })

function decision(stdout) {
  return JSON.parse(stdout).hookSpecificOutput
}

test("gated command -> ask", () => {
  const r = run(bash("terraform apply"))
  assert.equal(r.status, 0)
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.match(o.permissionDecisionReason, /^tf:/)
})

test("git status -> empty stdout, exit 0", () => {
  const r = run(bash("git status"))
  assert.equal(r.status, 0)
  assert.equal(r.stdout, "")
})

test("non-JSON stdin -> ask unparsable", () => {
  const r = run("not json")
  assert.equal(r.status, 0)
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.match(o.permissionDecisionReason, /^unparsable/)
})

test("invalid rules file -> ask gate-config", () => {
  const r = run(bash("git status"), { GATE_RULES: badRulesPath })
  assert.equal(r.status, 0)
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.match(o.permissionDecisionReason, /^gate-config/)
})

test("node unavailable -> ask", () => {
  const r = run(bash("git status"), { GATE_INFRA_NODE: "/nonexistent" })
  assert.equal(r.status, 0)
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.equal(o.permissionDecisionReason, "unparsable: node unavailable")
})

function fakeNode(name, body) {
  const p = join(dir, name)
  writeFileSync(p, `#!/usr/bin/env bash\n${body}\n`, { mode: 0o755 })
  return p
}

test("engine exits non-zero after partial JSON -> fixed ask only", () => {
  const fake = fakeNode(
    "partial.sh",
    `printf '{"hookSpecificOutput":{"permi'; exit 3`,
  )
  const r = run(bash("git status"), { GATE_INFRA_NODE: fake })
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.equal(o.permissionDecisionReason, "gate-config: engine failed")
})

test("engine exits 0 with empty stdout but did not run -> ask", () => {
  const fake = fakeNode("noop.sh", "exit 0")
  const r = run(bash("git status"), { GATE_INFRA_NODE: fake })
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.equal(o.permissionDecisionReason, "gate-config: engine failed")
})

test("empty stdin -> ask", () => {
  const r = run("", { GATE_INFRA_NODE: process.execPath })
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
})

// ---------------------------------------------------------------------------
// Script scan and Terraform fallback rules, against the shipped rules file
// ---------------------------------------------------------------------------

// A temporary project (an empty .git marks the root) with the given files.
function tempProject(files) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "gate-project-")))
  mkdirSync(join(root, ".git"))
  for (const [name, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, name)), { recursive: true })
    writeFileSync(join(root, name), content)
  }
  return root
}

// Stand-in for the source project's provision script: an entry script that names
// terraform and imports a deploy module, which shells out to cloudctl.
const provisionProject = () =>
  tempProject({
    "scripts/provision-cloud-app-dev.mjs": [
      'import { join } from "node:path"',
      'import { deploy } from "./deploy-cloud-app-dev.mjs"',
      "// Applies the terraform plan, then deploys.",
      "await deploy(join(process.cwd(), 'out'))",
      "",
    ].join("\n"),
    "scripts/deploy-cloud-app-dev.mjs": [
      'import { spawn } from "node:child_process"',
      "export async function deploy(dir) {",
      '  spawn("cloudctl", ["run", "deploy", "app", "--source", dir])',
      "}",
      "",
    ].join("\n"),
  })

function runShipped(command, cwd) {
  return run(bash(command, cwd), { GATE_RULES: shippedRules })
}

test("script scan: a script that runs terraform asks with script:", () => {
  const root = tempProject({
    "infra/cloud/apply.sh":
      "#!/bin/bash\nterraform -chdir=environments/dev apply dev.tfplan\n",
  })
  const r = runShipped("bash infra/cloud/apply.sh --apply", root)
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.equal(
    o.permissionDecisionReason,
    "script: infra/cloud/apply.sh runs terraform",
  )
})

test("script scan: a provision script that imports a cloudctl module asks with script:", () => {
  const r = runShipped(
    "node scripts/provision-cloud-app-dev.mjs",
    provisionProject(),
  )
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.match(
    o.permissionDecisionReason,
    /^script: scripts\/provision-cloud-app-dev\.mjs /,
  )
})

test("script scan: a Cloudflare-only script passes", () => {
  const root = tempProject({
    "scripts/cf.mjs":
      'await fetch("https://api.cloudflare.com/client/v4/x")\nspawn("wrangler", ["deploy"])\n',
  })
  assert.equal(runShipped("node scripts/cf.mjs", root).stdout, "")
})

test("terraform rule: apply, destroy and import ask with terraform:", () => {
  for (const command of [
    "terraform -chdir=infra/cloud/environments/dev apply dev.tfplan",
    "terraform destroy",
    "tofu import a b",
  ]) {
    const o = decision(runShipped(command, repoRoot).stdout)
    assert.equal(o.permissionDecision, "ask", command)
    assert.match(o.permissionDecisionReason, /^terraform:/, command)
  }
})

test("fallback passes: terraform plan/fmt/validate, --help, tests and git push", () => {
  for (const command of [
    "terraform plan",
    "terraform fmt",
    "terraform validate",
    "cloudctl sql instances create --help",
    "pnpm test:hooks",
    "node scripts/deploy-cloud-app-dev.test.mjs",
    "git push --force",
  ]) {
    assert.equal(runShipped(command, repoRoot).stdout, "", command)
  }
})

// ---------------------------------------------------------------------------
// Optional Jev layer, against a local HTTP mock. The wrapper runs through an
// async spawn so the in-process mock server can answer.
// ---------------------------------------------------------------------------

let jevServer
let jevUrl
let jevAnswer = { kind: "ok", probs: {} }
let jevBodies = []

before(async () => {
  jevServer = createServer((req, res) => {
    let raw = ""
    req.on("data", (d) => (raw += d))
    req.on("end", () => {
      try {
        jevBodies.push(JSON.parse(raw))
      } catch {
        jevBodies.push(null)
      }
      const a = jevAnswer
      if (a.kind === "hang") return // answered never; the hook times out
      if (a.kind === "status") {
        res.writeHead(a.status)
        return res.end()
      }
      res.writeHead(200, { "content-type": "application/json" })
      if (a.kind === "malformed") return res.end("{")
      res.end(
        JSON.stringify({
          answers: { cloud_change: { type: "choice", probabilities: a.probs } },
          usage: a.usage ?? { input_tokens: 1000, output_tokens: 10 },
        }),
      )
    })
  })
  await new Promise((resolve) => jevServer.listen(0, "127.0.0.1", resolve))
  jevUrl = `http://127.0.0.1:${jevServer.address().port}/v1/systemone`
})

after(() => {
  jevServer?.closeAllConnections()
  jevServer?.close()
})

// `answer` is a probabilities object, or { kind: "status" | "hang" | "malformed" }.
function runJev(stdin, answer, env = {}, { cwd } = {}) {
  jevAnswer = answer.kind ? answer : { kind: "ok", probs: answer }
  jevBodies = []
  return new Promise((resolve, reject) => {
    const child = spawn("bash", [wrapper], {
      cwd,
      env: {
        ...process.env,
        GATE_RULES: rulesPath,
        GATE_INFRA_NODE: process.execPath,
        CLAUDE_PROJECT_DIR: repoRoot,
        GATE_JEV: "1",
        GATE_JEV_LOG: "",
        TYPESAFE_API_KEY: "test-key",
        GATE_JEV_URL: jevUrl,
        GATE_JEV_TIMEOUT_MS: "5000",
        GATE_JEV_PROMPT: "cloud-change",
        ...env,
      },
    })
    let stdout = ""
    child.stdout.on("data", (d) => (stdout += d))
    child.on("error", reject)
    child.on("close", (status) =>
      resolve({
        status,
        stdout,
        hits: jevBodies.length,
        bodies: jevBodies.filter(Boolean),
      }),
    )
    child.stdin.end(stdin)
  })
}

const probs = (unrelated, read_only, cloud_or_data_change, destructive) => ({
  unrelated,
  read_only,
  cloud_or_data_change,
  destructive,
})

test("GATE_JEV unset -> rules-only output", async () => {
  for (const command of ["terraform apply", "git status"]) {
    const r = await runJev(bash(command), probs(0.01, 0.97, 0.01, 0.01), {
      GATE_JEV: "",
    })
    assert.equal(r.status, 0)
    assert.equal(r.stdout, run(bash(command)).stdout)
    assert.equal(r.hits, 0)
  }
})

test("jev: rule-matched command classified read_only 0.97 -> empty output", async () => {
  const r = await runJev(bash("terraform apply"), probs(0.01, 0.97, 0.01, 0.01))
  assert.equal(r.status, 0)
  assert.equal(r.stdout, "")
  assert.equal(r.hits, 1)
})

test("jev: in-scope command no rule matched, risk 0.55 -> ask", async () => {
  const r = await runJev(bash("terraform plan"), probs(0.15, 0.3, 0.25, 0.3))
  assert.equal(r.status, 0)
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.equal(o.permissionDecisionReason, "jev: destructive p=0.30 risk=0.55")
  assert.equal(r.hits, 1)
})

test("jev: a command outside every rule's programs goes to Jev and its risk asks", async () => {
  for (const command of ["git status", "node x.mjs", "rm -rf build"]) {
    const r = await runJev(bash(command), probs(0.1, 0.1, 0.6, 0.2))
    const o = decision(r.stdout)
    assert.equal(o.permissionDecision, "ask", command)
    assert.match(o.permissionDecisionReason, /^jev: /, command)
    assert.equal(r.hits, 1, command)
  }
})

test("jev: read_only 0.90 -> rule result stands", async () => {
  const gated = await runJev(
    bash("terraform apply"),
    probs(0.04, 0.9, 0.03, 0.03),
  )
  assert.match(decision(gated.stdout).permissionDecisionReason, /^tf:/)
  const passed = await runJev(
    bash("terraform plan"),
    probs(0.04, 0.9, 0.03, 0.03),
  )
  assert.equal(passed.stdout, "")
})

const dynamicRun = 'run(){ "$@" > log 2>&1; }; run format pnpm format:check'

test("jev: unparsable command classified read_only 0.97 -> empty output", async () => {
  for (const command of [dynamicRun, "echo 'open", 'eval "$CMD"']) {
    const r = await runJev(bash(command), probs(0.01, 0.97, 0.01, 0.01))
    assert.equal(r.status, 0)
    assert.equal(r.stdout, "", command)
    assert.equal(r.hits, 1, command)
  }
})

test("jev: unparsable command classified risky -> jev ask", async () => {
  const r = await runJev(bash(dynamicRun), probs(0.1, 0.2, 0.6, 0.1))
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.match(o.permissionDecisionReason, /^jev: cloud_or_data_change/)
  assert.equal(r.hits, 1)
})

test("jev: unsure or unreachable on unparsable command -> unparsable ask", async () => {
  const unsure = await runJev(bash(dynamicRun), probs(0.04, 0.9, 0.03, 0.03))
  assert.equal(
    decision(unsure.stdout).permissionDecisionReason,
    "unparsable: dynamic command word",
  )
  const down = await runJev(bash(dynamicRun), probs(0.01, 0.97, 0.01, 0.01), {
    GATE_JEV_URL: "http://127.0.0.1:1/v1/systemone",
  })
  assert.equal(
    decision(down.stdout).permissionDecisionReason,
    "unparsable: dynamic command word",
  )
})

test("jev: unparsable command without Jev still asks", async () => {
  const r = await runJev(bash(dynamicRun), probs(0.01, 0.97, 0.01, 0.01), {
    GATE_JEV: "",
  })
  assert.equal(
    decision(r.stdout).permissionDecisionReason,
    "unparsable: dynamic command word",
  )
  assert.equal(r.hits, 0)
})

test("jev: input-level unparsable and gate-config results still ask", async () => {
  const lifted = probs(0.01, 0.97, 0.01, 0.01)
  const noCommand = await runJev(
    JSON.stringify({ tool_name: "Bash", tool_input: {} }),
    lifted,
  )
  assert.match(
    decision(noCommand.stdout).permissionDecisionReason,
    /^unparsable:/,
  )
  const badJson = await runJev("not json", lifted)
  assert.match(
    decision(badJson.stdout).permissionDecisionReason,
    /^unparsable:/,
  )
  const badRules = await runJev(bash("git status"), lifted, {
    GATE_RULES: badRulesPath,
  })
  assert.match(
    decision(badRules.stdout).permissionDecisionReason,
    /^gate-config/,
  )
  assert.equal(noCommand.hits + badJson.hits + badRules.hits, 0)
})

test("jev: missing TYPESAFE_API_KEY -> ask gate-config", async () => {
  const r = await runJev(bash("git status"), probs(0.01, 0.97, 0.01, 0.01), {
    TYPESAFE_API_KEY: "",
  })
  assert.equal(r.status, 0)
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.match(o.permissionDecisionReason, /^gate-config: .*TYPESAFE_API_KEY/)
  assert.equal(r.hits, 0)
})

test("jev: unreachable service -> rule result stands", async () => {
  const r = await runJev(
    bash("terraform apply"),
    probs(0.01, 0.97, 0.01, 0.01),
    {
      GATE_JEV_URL: "http://127.0.0.1:1/v1/systemone",
    },
  )
  assert.match(decision(r.stdout).permissionDecisionReason, /^tf:/)
})

// ---------------------------------------------------------------------------
// Jev on every Bash and MCP call, against the shipped rules
// ---------------------------------------------------------------------------

const DBHOST_SQL = "mcp__plugin_dbhost_dbhost__execute_sql"
const CLOUDCTL_MCP = "mcp__cloudctl__run_cloudctl_command"
const ISSUE_EDIT = "mcp__tracker__editIssue"
const BROWSER_CLICK = "mcp__browser__click"

const mcpCall = (tool_name, tool_input = {}, cwd = repoRoot) =>
  JSON.stringify({ tool_name, tool_input, cwd })

const shipped = { GATE_RULES: shippedRules }
const unrelated = probs(0.97, 0.01, 0.01, 0.01)
const readOnly = probs(0.01, 0.97, 0.01, 0.01)
const risky = probs(0.1, 0.1, 0.6, 0.2)

test("the gate hook stays registered for Bash and every MCP tool only", () => {
  const hooks = JSON.parse(
    readFileSync(join(here, "..", "hooks", "hooks.json"), "utf8"),
  ).hooks
  const entries = hooks.PreToolUse.filter((e) => e.matcher === "Bash|mcp__.*")
  assert.equal(entries.length, 1)
  assert.match(entries[0].hooks[0].command, /\$\{CLAUDE_PLUGIN_ROOT\}\/hooks\/gate\.sh/)
  assert.ok(
    !hooks.PreToolUse.some(
      (e) =>
        e.matcher !== "Bash|mcp__.*" &&
        e.hooks.some((h) => /gate\.sh/.test(h.command)),
    ),
  )
})

test("jev: every Bash and MCP call makes exactly one request; file tools make none", async () => {
  for (const stdin of [
    bash("git status"),
    mcpCall(DBHOST_SQL, { query: "SELECT 1" }),
    mcpCall(CLOUDCTL_MCP, { args: ["run", "services", "list"] }),
    mcpCall(ISSUE_EDIT, { issueIdOrKey: "PROJ-1" }),
    mcpCall(BROWSER_CLICK, { action: "left_click" }),
  ]) {
    const r = await runJev(stdin, unrelated, shipped)
    assert.equal(r.hits, 1, stdin)
    assert.equal(r.status, 0)
  }
  for (const stdin of [
    mcpCall("Read", { file_path: "/x" }),
    mcpCall("Edit", { file_path: "/x", old_string: "a", new_string: "b" }),
    mcpCall("Write", { file_path: "/x", content: "y" }),
    mcpCall("Glob", { pattern: "*" }),
    mcpCall("Grep", { pattern: "x" }),
  ]) {
    const r = await runJev(stdin, risky, shipped)
    assert.equal(r.hits, 0, stdin)
    assert.equal(r.stdout, "", stdin)
  }
})

test("jev: risk above 0.5 asks for Bash and MCP calls no rule matched", async () => {
  for (const stdin of [
    bash("git status"),
    bash("node x.mjs"),
    mcpCall(ISSUE_EDIT, { issueIdOrKey: "PROJ-1" }),
  ]) {
    const o = decision((await runJev(stdin, risky, shipped)).stdout)
    assert.equal(o.permissionDecision, "ask", stdin)
    assert.match(o.permissionDecisionReason, /^jev: cloud_or_data_change/)
  }
})

test("jev: unrelated 0.97 gives no output", async () => {
  for (const stdin of [
    bash("git push --force"),
    bash("wrangler deploy"),
    mcpCall(ISSUE_EDIT, { issueIdOrKey: "PROJ-1", fields: { summary: "x" } }),
  ]) {
    const r = await runJev(stdin, unrelated, shipped)
    assert.equal(r.stdout, "", stdin)
    assert.equal(r.hits, 1)
  }
})

test("jev: read_only 0.97 lifts rule asks and script asks", async () => {
  const root = tempProject({ "plan.sh": "terraform plan -out x\n" })
  const cases = [
    [bash("cloudctl sql instances describe $P"), "cloudctl:"],
    [mcpCall(DBHOST_SQL, { query: "SELECT 1" }), "dbhost-mcp:"],
    [bash("bash plan.sh", root), "script:"],
  ]
  for (const [stdin, ruleReason] of cases) {
    const alone = run(stdin, { GATE_RULES: shippedRules })
    assert.ok(
      decision(alone.stdout).permissionDecisionReason.startsWith(ruleReason),
      stdin,
    )
    const r = await runJev(stdin, readOnly, shipped)
    assert.equal(r.stdout, "", stdin)
    assert.equal(r.hits, 1)
  }
})

test("jev: the request for a script carries the redacted script", async () => {
  const root = tempProject({
    "infra/cloud/apply.sh": [
      "#!/bin/bash",
      "export API_TOKEN=hunter2hunter2",
      "source .env.local",
      "terraform -chdir=environments/dev apply dev.tfplan",
      "",
    ].join("\n"),
  })
  const r = await runJev(
    bash("bash infra/cloud/apply.sh --apply", root),
    probs(0.05, 0.05, 0.9, 0),
    shipped,
  )
  const o = decision(r.stdout)
  assert.equal(o.permissionDecision, "ask")
  assert.match(o.permissionDecisionReason, /^jev: cloud_or_data_change/)
  const [state] = r.bodies.map((b) => b.state)
  assert.equal(state.command, "bash infra/cloud/apply.sh --apply")
  assert.equal(state.scripts.length, 1)
  assert.equal(state.scripts[0].path, "infra/cloud/apply.sh")
  assert.ok(!state.scripts[0].content.includes("hunter2"))
  assert.ok(state.scripts[0].content.includes("API_TOKEN=[REDACTED]"))
  assert.ok(!state.scripts[0].content.includes(".env.local"))
  assert.ok(state.scripts[0].content.includes("[line removed: .env reference]"))
  assert.ok(state.scripts[0].content.includes("terraform -chdir"))
})

test("jev: terraform test sends its test files and Jev can lift the terraform ask", async () => {
  const root = tempProject({
    "infra/env/main.tf": 'provider "acmecloud" {}\n',
    "infra/env/tests/iam.tftest.hcl":
      'mock_provider "acmecloud" {}\n\nrun "grants" {\n  command = apply\n}\n',
  })
  const command = "cd infra/env && terraform test"
  const unsure = await runJev(
    bash(command, root),
    probs(0.66, 0.2, 0.14, 0),
    shipped,
  )
  assert.match(
    decision(unsure.stdout).permissionDecisionReason,
    /^terraform: gated invocation/,
  )
  const [state] = unsure.bodies.map((b) => b.state)
  assert.deepEqual(
    state.scripts.map((s) => s.path),
    ["infra/env/tests/iam.tftest.hcl"],
  )
  assert.ok(state.scripts[0].content.includes('mock_provider "acmecloud"'))
  const sure = await runJev(
    bash(command, root),
    probs(0.1, 0.88, 0.02, 0),
    shipped,
  )
  assert.equal(sure.stdout.trim(), "")
})

test("jev: files the gate could not read reach Jev as notes", async () => {
  const outside = realpathSync(mkdtempSync(join(tmpdir(), "gate-outside-")))
  writeFileSync(join(outside, "deploy.sh"), "echo hi\n")
  const lines = Array.from({ length: 40 }, (_, k) => `import "./f${k}.mjs"`)
  const root = tempProject({
    "scripts/many.mjs": lines.join("\n") + "\n",
    ...Object.fromEntries(
      Array.from({ length: 40 }, (_, k) => [
        `scripts/f${k}.mjs`,
        "export {}\n",
      ]),
    ),
  })
  const r = await runJev(
    bash(`bash ${join(outside, "deploy.sh")}`, root),
    risky,
    shipped,
  )
  const state = r.bodies[0].state
  assert.deepEqual(state.scripts, [])
  assert.equal(state.notes.length, 1, JSON.stringify(state.notes))
  assert.match(state.notes[0], /not read: is outside the project$/)
  const capped = await runJev(
    bash("node scripts/many.mjs", root),
    risky,
    shipped,
  )
  assert.ok(
    capped.bodies[0].state.notes.some((n) =>
      /not read: more than 32 files$/.test(n),
    ),
    JSON.stringify(capped.bodies[0].state.notes),
  )
})

test("jev: imports are followed to depth 3, with per-file and total caps", async () => {
  const filler = "lorem ipsum ".repeat(6000)
  const root = tempProject({
    "scripts/provision.mjs":
      'import "./chain1.mjs"\nimport "./big.mjs"\nimport "./other.mjs"\n',
    "scripts/chain1.mjs": 'import "./chain2.mjs"\n',
    "scripts/chain2.mjs": 'import "./chain3.mjs"\n',
    "scripts/chain3.mjs": 'import "./chain4.mjs"\n',
    "scripts/chain4.mjs": "export {}\n",
    "scripts/big.mjs": `// ${filler}\n`,
    "scripts/other.mjs": "export {}\n",
  })
  const r = await runJev(
    bash("node scripts/provision.mjs", root),
    risky,
    shipped,
  )
  const state = r.bodies[0].state
  assert.deepEqual(
    state.scripts.map((s) => s.path),
    [
      "scripts/provision.mjs",
      "scripts/chain1.mjs",
      "scripts/big.mjs",
      "scripts/other.mjs",
      "scripts/chain2.mjs",
      "scripts/chain3.mjs",
    ].slice(0, state.scripts.length),
  )
  assert.ok(!state.scripts.some((s) => s.path.includes("chain4")))
  assert.ok(state.notes.some((n) => n === "scripts/big.mjs cut at 64 KB"))
  assert.ok(state.notes.some((n) => /^scripts cut at 64 KB total: /.test(n)))
  const bytes = state.scripts.reduce(
    (n, s) => n + Buffer.byteLength(s.content),
    0,
  )
  assert.ok(bytes <= 65536, String(bytes))
})

test("jev: a provision script is sent with its imports", async () => {
  const r = await runJev(
    bash("node scripts/provision-cloud-app-dev.mjs", provisionProject()),
    risky,
    shipped,
  )
  const paths = r.bodies[0].state.scripts.map((s) => s.path)
  assert.equal(paths[0], "scripts/provision-cloud-app-dev.mjs")
  assert.ok(
    paths.includes("scripts/deploy-cloud-app-dev.mjs"),
    paths.join(),
  )
})

test("jev: MCP calls send the tool name and the redacted input", async () => {
  const r = await runJev(
    mcpCall(DBHOST_SQL, {
      project_id: "abcdefghijklmnopqrst",
      query: "INSERT INTO t (a) VALUES ('secret value')",
      access_token: "tok-123",
    }),
    unrelated,
    shipped,
  )
  const state = r.bodies[0].state
  assert.equal(state.tool, DBHOST_SQL)
  assert.ok(!state.input.includes("secret value"))
  assert.ok(!state.input.includes("tok-123"))
  assert.ok(state.input.includes("INSERT INTO t"))
  assert.deepEqual(state.notes, [])
})

test("jev failures give the rule result for Bash and MCP calls", async () => {
  const modes = {
    hang: [{ kind: "hang" }, { GATE_JEV_TIMEOUT_MS: "200" }],
    429: [{ kind: "status", status: 429 }, { GATE_JEV_TIMEOUT_MS: "400" }],
    529: [{ kind: "status", status: 529 }, { GATE_JEV_TIMEOUT_MS: "400" }],
    401: [{ kind: "status", status: 401 }, {}],
    malformed: [{ kind: "malformed" }, {}],
  }
  for (const [mode, [answer, env]] of Object.entries(modes)) {
    const go = (stdin) => runJev(stdin, answer, { ...shipped, ...env })
    const gated = await go(bash("terraform apply"))
    assert.match(
      decision(gated.stdout).permissionDecisionReason,
      /^terraform:/,
      mode,
    )
    assert.equal((await go(bash("git status"))).stdout, "", mode)
    const sql = await go(mcpCall(DBHOST_SQL, { query: "SELECT 1" }))
    assert.match(
      decision(sql.stdout).permissionDecisionReason,
      /^dbhost-mcp:/,
      mode,
    )
    assert.equal(
      (await go(mcpCall(ISSUE_EDIT, { issueIdOrKey: "PROJ-1" }))).stdout,
      "",
      mode,
    )
  }
})

test("jev: an MCP call without its args and a gate-config result never reach Jev", async () => {
  const noArgs = await runJev(mcpCall(CLOUDCTL_MCP, {}), unrelated, shipped)
  assert.match(decision(noArgs.stdout).permissionDecisionReason, /^unparsable:/)
  const badRules = await runJev(mcpCall(ISSUE_EDIT, {}), unrelated, {
    GATE_RULES: badRulesPath,
  })
  assert.match(
    decision(badRules.stdout).permissionDecisionReason,
    /^gate-config/,
  )
  assert.equal(noArgs.hits + badRules.hits, 0)
})

test("jev audit log: records carry tool, usage and latencyMs", async () => {
  const logPath = join(dir, "audit.jsonl")
  const r = await runJev(
    mcpCall(DBHOST_SQL, { query: "SELECT 1" }),
    readOnly,
    { ...shipped, GATE_JEV_LOG: logPath },
  )
  assert.equal(r.stdout, "")
  const [record] = readFileSync(logPath, "utf8")
    .trim()
    .split("\n")
    .map((l) => JSON.parse(l))
  assert.equal(record.tool, DBHOST_SQL)
  assert.deepEqual(record.usage, { input_tokens: 1000, output_tokens: 10 })
  assert.equal(typeof record.latencyMs, "number")
  assert.equal(record.decision, "pass")
  assert.match(record.rule, /^dbhost-mcp:/)
})
