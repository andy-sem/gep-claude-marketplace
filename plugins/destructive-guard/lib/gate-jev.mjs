// Optional Jev (TypeSafe) layer for the approval gate. Loaded by
// gate-engine.mjs only when GATE_JEV is set. For every Bash command and every MCP
// call it asks Jev whether the call changes cloud services, remote infrastructure
// or databases. Jev can add an `ask` or lift a rule `ask` (no output, so Claude Code's own
// permission rules decide); it never emits an `allow`. Any request failure leaves
// the rule result unchanged.

import { appendFileSync } from "node:fs"

export const JEV_URL = "https://api.typesafe.ai/v1/systemone"

const DEFAULTS = {
  allowThreshold: 0.95,
  escalateThreshold: 0.5,
  model: "jev-latest",
  timeoutMs: 1500,
}
const MAX_TIMEOUT_MS = 30000
const MAX_COMMAND_CHARS = 8000
const MAX_INPUT_CHARS = 8000
const MAX_SCRIPTS_BYTES = 65536
const QUESTION = "cloud_change"
const CHOICES = [
  "unrelated",
  "read_only",
  "cloud_or_data_change",
  "destructive",
]
const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"])

export class JevConfigError extends Error {
  constructor(message) {
    super(message)
    this.name = "JevConfigError"
  }
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// Empty optional variables count as unset.
function optional(env, name) {
  const value = env[name]
  return value === undefined || value.trim() === "" ? undefined : value.trim()
}

function probability(env, name, fallback) {
  const raw = optional(env, name)
  if (raw === undefined) return fallback
  const n = /^(0(\.\d+)?|1(\.0+)?|\.\d+)$/.test(raw) ? Number(raw) : NaN
  if (!(n >= 0 && n <= 1))
    throw new JevConfigError(`${name} must be a number from 0 to 1`)
  return n
}

// Returns null when Jev is off. Throws JevConfigError when Jev is on and a
// variable is missing or invalid, so the gate can ask instead of guessing.
export function readJevConfig(env) {
  const toggle = optional(env, "GATE_JEV")
  if (toggle === undefined || toggle === "0") return null
  if (toggle !== "1") throw new JevConfigError("GATE_JEV must be 1 or unset")

  const apiKey = optional(env, "TYPESAFE_API_KEY")
  if (!apiKey)
    throw new JevConfigError("GATE_JEV=1 but TYPESAFE_API_KEY is not set")

  const rawTimeout = optional(env, "GATE_JEV_TIMEOUT_MS")
  const timeoutMs =
    rawTimeout === undefined ? DEFAULTS.timeoutMs : Number(rawTimeout)
  if (
    !/^\d+$/.test(rawTimeout ?? "0") ||
    timeoutMs < 1 ||
    timeoutMs > MAX_TIMEOUT_MS
  )
    throw new JevConfigError(
      `GATE_JEV_TIMEOUT_MS must be an integer from 1 to ${MAX_TIMEOUT_MS}`,
    )

  const url = optional(env, "GATE_JEV_URL") ?? JEV_URL
  let parsed
  try {
    parsed = new URL(url)
  } catch {
    throw new JevConfigError("GATE_JEV_URL is not a valid URL")
  }
  // The API key must not travel in clear text, except to a local test server.
  if (
    parsed.protocol !== "https:" &&
    !(parsed.protocol === "http:" && LOOPBACK.has(parsed.hostname))
  )
    throw new JevConfigError("GATE_JEV_URL must use https")

  return {
    apiKey,
    url,
    model: optional(env, "GATE_JEV_MODEL") ?? DEFAULTS.model,
    allowThreshold: probability(
      env,
      "GATE_JEV_ALLOW_THRESHOLD",
      DEFAULTS.allowThreshold,
    ),
    escalateThreshold: probability(
      env,
      "GATE_JEV_ESCALATE_THRESHOLD",
      DEFAULTS.escalateThreshold,
    ),
    timeoutMs,
    logPath: optional(env, "GATE_JEV_LOG"),
  }
}

// ---------------------------------------------------------------------------
// Redaction
// ---------------------------------------------------------------------------

const R = "[REDACTED]"
const ENV_LINE_REMOVED = "[line removed: .env reference]"
const SECRET_NAME =
  "[\\w-]*(?:token|passw(?:or)?d|pwd|secret|api[_-]?key|apikey|auth\\w*|credential|private[_-]?key)[\\w-]*"
const SECRET_KEY_RE = new RegExp(`^${SECRET_NAME}$`, "i")
const SQL_KEYS = new Set(["query", "sql", "statement"])

// Commands that mention .env files (`.env`, `apps/x/.env.local`, `.envrc`)
// are never sent.
export function referencesEnvFile(command) {
  return /(^|[^A-Za-z0-9])\.env/.test(command)
}

function looksEncoded(run) {
  return /[0-9]/.test(run) && /[A-Z]/.test(run) && /[a-z]/.test(run)
}

// The redaction rules shared by commands, scripts and MCP inputs. `envAssignments`
// is off for SQL, where `id=5` is not a shell assignment.
function redactText(text, { envAssignments = true } = {}) {
  let out = text
    // https://user:pass@host -> https://[REDACTED]@host
    .replace(/\b([a-z][a-z0-9+.-]*:\/\/)[^\s/@'"]+@/gi, `$1${R}@`)
    .replace(/\b(Bearer|Basic|Token)\s+[^\s'"]+/gi, `$1 ${R}`)
    // NAME=value / NAME: value where NAME looks like a secret
    .replace(
      new RegExp(
        `(${SECRET_NAME})(\\s*[=:]\\s*)("[^"]*"|'[^']*'|[^\\s'"]+)`,
        "gi",
      ),
      `$1$2${R}`,
    )
    // --password value / -token value
    .replace(
      new RegExp(
        `(\\s--?${SECRET_NAME})(\\s+)("[^"]*"|'[^']*'|[^\\s'"-][^\\s'"]*)`,
        "gi",
      ),
      `$1$2${R}`,
    )
  if (envAssignments) {
    // Environment assignments: FOO=bar cmd, export FOO=bar, env FOO=bar cmd
    out = out.replace(
      /(^|[\s;&|(])([A-Za-z_][A-Za-z0-9_]*)=("[^"]*"|'[^']*'|[^\s;&|)]*)/g,
      `$1$2=${R}`,
    )
  }
  return out
    .replace(/\b[0-9a-f]{32,}\b/gi, R)
    .replace(/[A-Za-z0-9+/_-]{32,}={0,2}/g, (run) =>
      looksEncoded(run) ? R : run,
    )
}

// Returns the command with secrets replaced, or null when it must not be sent.
export function redact(command) {
  if (referencesEnvFile(command)) return null
  return redactText(command)
}

// Lines that reference an .env file are removed instead of skipping the call.
function dropEnvLines(text) {
  return text
    .split("\n")
    .map((line) => (referencesEnvFile(line) ? ENV_LINE_REMOVED : line))
    .join("\n")
}

// Script and file contents: `.env` lines removed, then the shared rules. The call
// is never skipped.
export function redactScript(text) {
  return redactText(dropEnvLines(text))
}

// Single-quoted literals (with '' escapes) and dollar-quoted bodies hold data, not
// structure: Jev needs the statement kind, not the values.
function redactSqlLiterals(sql) {
  return sql
    .replace(
      /(\$[A-Za-z_]\w*\$|\$\$)[\s\S]*?\1/g,
      (_m, tag) => `${tag}${R}${tag}`,
    )
    .replace(/'(?:[^']|'')*'/g, `'${R}'`)
}

function redactMcpValue(value, key) {
  if (typeof value === "string") {
    const text = dropEnvLines(value)
    return SQL_KEYS.has(key)
      ? redactText(redactSqlLiterals(text), { envAssignments: false })
      : redactText(text)
  }
  if (Array.isArray(value)) return value.map((v) => redactMcpValue(v, key))
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [
        k,
        SECRET_KEY_RE.test(k) ? R : redactMcpValue(v, k),
      ]),
    )
  }
  return value
}

// An MCP tool input as redacted JSON text.
export function redactMcpInput(toolInput) {
  return JSON.stringify(redactMcpValue(toolInput ?? {}, "")) ?? "{}"
}

// ---------------------------------------------------------------------------
// Jev request
// ---------------------------------------------------------------------------

// Supporting facts sent with every call.
const CONTEXT = {
  environment:
    "A coding agent runs shell commands and MCP tool calls in a developer's repository. The tool is named in 'tool'.",
  projects:
    "The repository may manage cloud resources (for example with Terraform, cloud CLIs or CI workflows that deploy) and may connect to remote databases.",
  policy:
    "Only creating, changing, deploying, granting access to or deleting cloud resources, remote infrastructure or database data needs a person. Reading them is safe. Git, Jira, browser and local file actions are unrelated, even when they change something.",
  inputs:
    "'command' is a Bash command, 'scripts' holds the contents of project files that command runs or imports (path and content), including the *.tftest.hcl files a terraform test command runs, 'input' is the JSON input of an MCP tool call, and 'notes' lists anything that was cut. Judge what the call does, including what the scripts do.",
}

// Each option has a description and illustrative examples. The examples are
// not exhaustive; judge the call by what it does.
const CRITERIA = {
  unrelated: {
    description:
      "Does not touch cloud services, remote infrastructure or databases, even if it changes something else (local files, git, Jira, the browser)",
    examples: [
      "git push --force origin main",
      "wrangler dev",
      "pnpm test",
      "node scripts/format.mjs, a script that only reformats local files",
      "mcp__plugin_atlassian_atlassian__editJiraIssue with a new summary",
      "mcp__claude-in-chrome__computer with a click",
    ],
  },
  read_only: {
    description:
      "Only reads or inspects cloud, infrastructure or database state, with no change to resources or data",
    examples: [
      "aws ec2 describe-instances",
      "kubectl get pods",
      "terraform plan",
      "bash plan.sh, a script that only runs terraform plan",
      "terraform test, where every test file in 'scripts' declares mock_provider for each provider, so no run block reaches the real cloud",
      "psql -c 'SELECT count(*) FROM users'",
      "an MCP database tool such as mcp__db__execute_sql with SELECT * FROM users LIMIT 5",
      "an MCP cloud tool such as mcp__cloud__run_command with args services list",
    ],
  },
  cloud_or_data_change: {
    description:
      "Creates, changes, deploys or grants access to cloud resources, remote infrastructure or database data, directly or through a script, Terraform or a workflow",
    examples: [
      "kubectl apply -f deploy.yaml",
      "terraform apply",
      "terraform test, where a test file has a run block with command = apply (the default) and a real, unmocked provider",
      "bash infra/apply.sh --apply",
      "node scripts/provision-dev.mjs, a script that creates cloud resources",
      "gh workflow run deploy-dev.yml",
      "psql -c 'UPDATE users SET ...'",
      "mcp__db__execute_sql with INSERT INTO users ... or UPDATE users SET ...",
      "mcp__db__apply_migration",
      "mcp__cloud__run_command with args deploy api",
    ],
  },
  destructive: {
    description:
      "Deletes or overwrites cloud resources, remote infrastructure or database data, or is hard to undo",
    examples: [
      "terraform destroy",
      "terraform state rm aws_db_instance.main",
      "aws s3 rm --recursive s3://bucket/path",
      "kubectl delete namespace prod",
      "mcp__db__execute_sql with DROP TABLE users, DELETE FROM users or TRUNCATE users",
      "psql -c 'DROP TABLE users'",
    ],
  },
}

const INSTRUCTIONS =
  "Does this call change cloud services, remote infrastructure or databases?"

function requestBody(state, model) {
  return {
    model,
    state: { ...state, context: CONTEXT },
    questions: {
      [QUESTION]: {
        type: "choice",
        instructions: INSTRUCTIONS,
        criteria: CRITERIA,
      },
    },
  }
}

const byteLength = (text) => Buffer.byteLength(text)

// Scripts go to Jev in collection order, redacted, up to 64 KB in total: the file
// that crosses the cap is cut, the rest are left out. The notes say what was cut.
function scriptsPayload(files) {
  const scripts = []
  const notes = []
  let used = 0
  let cutPath = null
  const omitted = []
  for (const file of files) {
    const content = redactScript(file.content)
    const size = byteLength(content)
    if (file.truncated) notes.push(`${file.path} cut at 64 KB`)
    if (cutPath || omitted.length) {
      omitted.push(file.path)
    } else if (used + size <= MAX_SCRIPTS_BYTES) {
      scripts.push({ path: file.path, content })
      used += size
    } else if (used < MAX_SCRIPTS_BYTES) {
      const room = MAX_SCRIPTS_BYTES - used
      scripts.push({
        path: file.path,
        content: Buffer.from(content).subarray(0, room).toString("utf8"),
      })
      used = MAX_SCRIPTS_BYTES
      cutPath = file.path
    } else {
      omitted.push(file.path)
    }
  }
  if (cutPath || omitted.length) {
    const parts = []
    if (cutPath) parts.push(`${cutPath} truncated`)
    if (omitted.length) parts.push(`omitted: ${omitted.join(", ")}`)
    notes.push(`scripts cut at 64 KB total: ${parts.join("; ")}`)
  }
  return { scripts, notes }
}

// One note per file the gate could not read safely, so that Jev does not take an
// empty `scripts` list for "nothing to read". Exempt files are left out, and so are
// files cut at 64 KB (the cut is noted already). The text is redacted like a script.
function problemNotes(problems) {
  return problems
    .filter((p) => !p.exempt && p.reason !== "exceeds 64 KB")
    .map((p) => `${redactScript(p.path)} not read: ${p.reason}`)
}

// The request state for a call, or null when the call must not be sent (a Bash
// command that references an .env file). `call` is
// { tool: "Bash", command, scripts, problems } or { tool, input }.
export function buildState(call) {
  if (call.tool === "Bash") {
    const redacted = redact(call.command)
    if (redacted === null) return null
    const notes = []
    if (redacted.length > MAX_COMMAND_CHARS) {
      notes.push(
        `command cut to ${MAX_COMMAND_CHARS} of ${redacted.length} characters`,
      )
    }
    const { scripts, notes: scriptNotes } = scriptsPayload(call.scripts ?? [])
    return {
      tool: "Bash",
      command: redacted.slice(0, MAX_COMMAND_CHARS),
      scripts,
      notes: [...notes, ...scriptNotes, ...problemNotes(call.problems ?? [])],
    }
  }
  const input = redactMcpInput(call.input)
  const notes = []
  if (input.length > MAX_INPUT_CHARS) {
    notes.push(`input cut to ${MAX_INPUT_CHARS} of ${input.length} characters`)
  }
  return { tool: call.tool, input: input.slice(0, MAX_INPUT_CHARS), notes }
}

// Returns the probabilities map, or null when the response is malformed.
export function parseAnswer(json) {
  const answer = json?.answers?.[QUESTION]
  const probs = answer?.probabilities
  if (answer?.type !== "choice" || !probs || typeof probs !== "object")
    return null
  let sum = 0
  for (const choice of CHOICES) {
    const p = probs[choice]
    if (typeof p !== "number" || !(p >= 0 && p <= 1)) return null
    sum += p
  }
  if (Math.abs(sum - 1) > 0.05) return null
  return Object.fromEntries(CHOICES.map((c) => [c, probs[c]]))
}

function retryDelay(attempt, retryAfter) {
  const seconds = Number(retryAfter)
  if (retryAfter && Number.isFinite(seconds) && seconds >= 0)
    return seconds * 1000
  return 100 * 2 ** (attempt - 1) + Math.floor(Math.random() * 50)
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Calls Jev within one overall time budget (retries included). Never throws.
// Returns { probabilities, usage, latencyMs } or { error, latencyMs }; latencyMs
// covers all attempts and `usage` is the token usage Jev reports, or null.
export async function askJev(state, cfg, { fetchImpl = fetch } = {}) {
  const started = Date.now()
  const deadline = started + cfg.timeoutMs
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), cfg.timeoutMs)
  const body = JSON.stringify(requestBody(state, cfg.model))
  const fail = (error) => ({ error, latencyMs: Date.now() - started })
  try {
    for (let attempt = 1; ; attempt++) {
      let res
      try {
        res = await fetchImpl(cfg.url, {
          method: "POST",
          headers: {
            authorization: `Bearer ${cfg.apiKey}`,
            "content-type": "application/json",
          },
          body,
          signal: controller.signal,
        })
      } catch {
        return fail(controller.signal.aborted ? "timeout" : "network")
      }
      if (res.status === 429 || res.status === 529) {
        const delay = retryDelay(attempt, res.headers?.get?.("retry-after"))
        if (Date.now() + delay >= deadline) return fail(`http ${res.status}`)
        await wait(delay)
        continue
      }
      if (!res.ok) return fail(`http ${res.status}`)
      let json
      try {
        json = await res.json()
      } catch {
        return fail(controller.signal.aborted ? "timeout" : "malformed")
      }
      const probabilities = parseAnswer(json)
      if (!probabilities) return fail("malformed")
      return {
        probabilities,
        usage: json.usage ?? null,
        latencyMs: Date.now() - started,
      }
    }
  } finally {
    clearTimeout(timer)
  }
}

// ---------------------------------------------------------------------------
// Decision
// ---------------------------------------------------------------------------

const fmt = (p) => p.toFixed(2)

// "ask" (risk above the escalate threshold), "pass" (lift any rule ask, safe at or
// above the allow threshold) or null (no Jev decision). Jev never emits `allow`.
export function jevDecision(probs, cfg) {
  const risk = probs.destructive + probs.cloud_or_data_change
  if (risk > cfg.escalateThreshold) {
    const top =
      probs.destructive >= probs.cloud_or_data_change
        ? "destructive"
        : "cloud_or_data_change"
    return {
      decision: "ask",
      reason: `jev: ${top} p=${fmt(probs[top])} risk=${fmt(risk)}`,
    }
  }
  const safe = probs.unrelated + probs.read_only
  if (safe >= cfg.allowThreshold) {
    const top = probs.unrelated >= probs.read_only ? "unrelated" : "read_only"
    return {
      decision: "pass",
      reason: `jev: ${top} p=${fmt(probs[top])} safe=${fmt(safe)}`,
    }
  }
  return null
}

function audit(cfg, record) {
  if (!cfg.logPath) return
  try {
    appendFileSync(
      cfg.logPath,
      JSON.stringify({ ts: new Date().toISOString(), ...record }) + "\n",
    )
  } catch {}
}

// Applies Jev to a Bash command or an MCP call on top of the rule result and
// returns the final gate result: an ask, or null for no output.
export async function runJev(call, ruleResult, cfg, deps) {
  const rule = ruleResult?.reason ?? null
  const state = buildState(call)
  const tool = call.tool
  if (state === null) {
    audit(cfg, {
      tool,
      command: null,
      rule,
      outcome: "skipped: .env reference",
      latencyMs: 0,
    })
    return ruleResult
  }
  const sent =
    tool === "Bash"
      ? { command: state.command, scripts: state.scripts.map((s) => s.path) }
      : { input: state.input }
  const { probabilities, usage, error, latencyMs } = await askJev(
    state,
    cfg,
    deps,
  )
  if (!probabilities) {
    audit(cfg, {
      tool,
      ...sent,
      rule,
      outcome: `fallback: ${error}`,
      latencyMs,
    })
    return ruleResult
  }
  const jev = jevDecision(probabilities, cfg)
  const final =
    jev?.decision === "ask"
      ? { decision: "ask", reason: jev.reason }
      : jev?.decision === "pass"
        ? null
        : ruleResult
  audit(cfg, {
    tool,
    ...sent,
    probabilities,
    rule,
    jev: jev?.reason ?? null,
    decision: final ? final.decision : "pass",
    usage,
    latencyMs,
  })
  return final
}
