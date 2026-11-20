#!/usr/bin/env node
// Dry run for destructive-guard: what would the gate do with a call, and what
// is the effective configuration? Used by the `check` skill. Builds the config
// exactly like the hook (readConfig → buildRules → gate), never runs the call,
// and by default never contacts Jev (`--jev` opts in to a real request).
//
//   check.mjs [--json] [--jev] [--cwd DIR] -- <command…>       a Bash command
//   check.mjs [--json] [--jev] --mcp <tool> [<json input>]     an MCP call
//   check.mjs [--json] --config                                 effective config
//
// No call given → --config. Exit code 0 on success (whatever the decision),
// 2 on usage errors.

import { realpathSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { gate, RulesError } from "./gate-engine.mjs"
import { ConfigError, buildRules, readConfig } from "./config.mjs"

const JEV_VARS = /^(GATE_JEV|TYPESAFE_API_KEY)/

export class UsageError extends Error {}

export function parseArgs(argv) {
  const opts = { json: false, jev: false, cwd: undefined, mode: "config" }
  const args = [...argv]
  while (args.length) {
    const a = args.shift()
    if (a === "--json") opts.json = true
    else if (a === "--jev") opts.jev = true
    else if (a === "--config") opts.mode = "config"
    else if (a === "--cwd") {
      if (!args.length) throw new UsageError("--cwd needs a directory")
      opts.cwd = args.shift()
    } else if (a === "--mcp") {
      const tool = args.shift()
      if (!tool || !tool.startsWith("mcp__"))
        throw new UsageError("--mcp needs a tool name starting with mcp__")
      const raw = args.length ? args.join(" ") : "{}"
      let input
      try {
        input = JSON.parse(raw)
      } catch {
        throw new UsageError(`MCP input is not valid JSON: ${raw}`)
      }
      if (input === null || typeof input !== "object" || Array.isArray(input))
        throw new UsageError("MCP input must be a JSON object")
      return { ...opts, mode: "mcp", tool, input }
    } else if (a === "--") {
      if (!args.length) throw new UsageError("no command after --")
      return { ...opts, mode: "bash", command: args.join(" ") }
    } else if (a.startsWith("--")) {
      throw new UsageError(`unknown option ${a}`)
    } else {
      return { ...opts, mode: "bash", command: [a, ...args].join(" ") }
    }
  }
  return opts
}

// Jev settings for display; never includes the API key itself.
async function jevSummary(env) {
  if (!env.GATE_JEV || env.GATE_JEV.trim() === "" || env.GATE_JEV.trim() === "0")
    return { enabled: false }
  try {
    const { readJevConfig } = await import("./gate-jev.mjs")
    const cfg = readJevConfig(env)
    if (!cfg) return { enabled: false }
    const { apiKey, prompt, ...rest } = cfg
    return {
      enabled: true,
      ...rest,
      apiKey: apiKey ? "[set]" : "[missing]",
      prompt: env.GATE_JEV_PROMPT?.trim() || "destructive",
      question: prompt.question,
      ask: prompt.ask,
      safe: prompt.safe,
    }
  } catch (e) {
    return { enabled: true, error: `gate-config: ${e?.message ?? e}` }
  }
}

// Effective configuration plus the loaded rule ids, or the config error the
// hook would answer with.
export async function effectiveConfig(env = process.env) {
  const out = {}
  try {
    const config = readConfig(env)
    Object.assign(out, config)
    if (config.enabled) {
      const rules = buildRules(config)
      out.ruleIds = (rules.rules ?? []).map((r) => r.id).filter(Boolean)
    }
  } catch (e) {
    if (!(e instanceof ConfigError || e instanceof RulesError)) throw e
    out.error = `gate-config: ${e.message}`
  }
  out.jev = await jevSummary(env)
  return out
}

// The gate's answer for one call. Never executes it.
export async function checkCall(call, { env = process.env, cwd, jev = false } = {}) {
  const input =
    call.mode === "bash"
      ? { tool_name: "Bash", tool_input: { command: call.command } }
      : { tool_name: call.tool, tool_input: call.input }
  if (cwd) input.cwd = cwd
  const gateEnv = jev
    ? env
    : Object.fromEntries(Object.entries(env).filter(([k]) => !JEV_VARS.test(k)))
  const target =
    call.mode === "bash" ? { tool: "Bash", command: call.command } : { tool: call.tool, input: call.input }

  let config
  try {
    config = readConfig(env, { cwd: cwd ?? process.cwd() })
  } catch (e) {
    if (!(e instanceof ConfigError)) throw e
    return { ...target, ...answer({ decision: "ask", reason: `gate-config: ${e.message}` }), rule: null }
  }
  if (!config.enabled) return { ...target, decision: "none", reason: "gate disabled (GATE_ENABLED=0)", source: null, rule: null }
  let rules
  try {
    rules = buildRules(config)
  } catch (e) {
    if (!(e instanceof ConfigError || e instanceof RulesError)) throw e
    return { ...target, ...answer({ decision: "ask", reason: `gate-config: ${e.message}` }), rule: null }
  }
  const trace = {}
  const result = await gate(input, rules, { env: gateEnv, cwd, strict: config.strict, trace })
  const kind = call.mode === "bash" ? "bash" : "mcp"
  const jevInfo = await jevSummary(env)
  const jevScope = jevInfo.enabled && !jevInfo.error ? jevInfo.scope.includes(kind) : false
  return {
    ...target,
    ...answer(result),
    rule: trace.rule ? answer(trace.rule) : null,
    jev: jev ? "consulted" : jevScope ? "would be consulted (pass --jev)" : "off",
  }
}

// { decision, reason, source }: source is the rule id or the gate's own tag
// (script, unparsable, gate-config, jev) taken from the reason prefix.
function answer(result) {
  if (!result) return { decision: "none", reason: null, source: null }
  const i = result.reason.indexOf(": ")
  return { decision: result.decision, reason: result.reason, source: i > 0 ? result.reason.slice(0, i) : result.reason }
}

function formatCheck(r) {
  const what = r.tool === "Bash" ? `Bash: ${r.command}` : `${r.tool} ${JSON.stringify(r.input)}`
  const lines = [what]
  if (r.decision === "ask") lines.push(`decision: ask`, `source:   ${r.source}`, `reason:   ${r.reason}`)
  else lines.push(`decision: none (the gate has no opinion; Claude Code's own permission rules decide)`)
  if (r.reason && r.decision !== "ask") lines.push(`reason:   ${r.reason}`)
  if (r.rule && r.rule.reason !== r.reason) lines.push(`rules alone: ${r.rule.decision} (${r.rule.reason})`)
  if (r.jev) lines.push(`jev:      ${r.jev}`)
  return lines.join("\n")
}

function formatConfig(c) {
  const lines = []
  if (c.error) lines.push(`ERROR: ${c.error} (every gated call asks)`)
  if (c.enabled !== undefined) {
    lines.push(
      `enabled:       ${c.enabled}`,
      `packs:         ${c.packs.join(", ") || "(none)"}`,
      `rules files:   ${c.rulesFiles.join(", ") || "(none)"}`,
      `disabled ids:  ${c.disableRules.join(", ") || "(none)"}`,
      `strict:        ${c.strict}`,
      `env guard:     ${c.envGuard}`,
      `log:           ${c.log ?? "(off)"}`,
    )
    if (c.ruleIds) lines.push(`rules (${c.ruleIds.length}): ${c.ruleIds.join(", ")}`)
  }
  const j = c.jev
  if (!j.enabled) lines.push("jev:           off")
  else if (j.error) lines.push(`jev:           ERROR ${j.error}`)
  else
    lines.push(
      `jev:           on (${j.url}, model ${j.model}, api key ${j.apiKey})`,
      `  prompt:      ${j.prompt} (question ${j.question}; ask ${j.ask.join(",")}; safe ${j.safe.join(",")})`,
      `  scope:       ${j.scope.join(",")}   can lift: ${j.canLift}`,
      `  thresholds:  allow ${j.allowThreshold}, escalate ${j.escalateThreshold}; timeout ${j.timeoutMs}ms`,
    )
  return lines.join("\n")
}

export async function run(argv, { env = process.env, cwd = process.cwd() } = {}) {
  let opts
  try {
    opts = parseArgs(argv)
  } catch (e) {
    if (e instanceof UsageError) return { code: 2, out: `usage error: ${e.message}` }
    throw e
  }
  if (opts.mode === "config") {
    const c = await effectiveConfig(env)
    return { code: 0, out: opts.json ? JSON.stringify(c, null, 2) : formatConfig(c) }
  }
  const r = await checkCall(opts, { env, cwd: opts.cwd ?? cwd, jev: opts.jev })
  return { code: 0, out: opts.json ? JSON.stringify(r, null, 2) : formatCheck(r) }
}

function isMain() {
  try {
    return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))
  } catch {
    return false
  }
}

if (isMain()) {
  const { code, out } = await run(process.argv.slice(2))
  process.stdout.write(out + "\n")
  process.exit(code)
}
