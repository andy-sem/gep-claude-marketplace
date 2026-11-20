// Effective destructive-guard configuration from environment variables. All
// env parsing for the rules layer lives here; the Jev variables are read by
// gate-jev.mjs. readConfig() is pure (env in, config out) and throws
// ConfigError for any value it does not understand, so the gate can fail
// closed instead of guessing.

import { readdirSync } from "node:fs"
import {
  DEFAULT_PACKS,
  PACKS_DIR,
  RulesError,
  composeRules,
  packPath,
  parseRules,
} from "./gate-engine.mjs"
import { projectPath } from "./paths.mjs"

export class ConfigError extends Error {
  constructor(message) {
    super(message)
    this.name = "ConfigError"
  }
}

export const DEFAULT_CHECKS = DEFAULT_PACKS.filter((p) => p !== "base")

const TRUE = new Set(["1", "true", "yes", "on"])
const FALSE = new Set(["0", "false", "no", "off"])

// Unset or empty means "use the default".
function value(env, name) {
  const v = env[name]
  if (v === undefined || v === null) return undefined
  const s = String(v).trim()
  return s === "" ? undefined : s
}

function flag(env, name, fallback) {
  const v = value(env, name)
  if (v === undefined) return fallback
  const lower = v.toLowerCase()
  if (TRUE.has(lower)) return true
  if (FALSE.has(lower)) return false
  throw new ConfigError(`${name} must be 0 or 1, got "${v}"`)
}

function list(v, sep) {
  return v
    .split(sep)
    .map((s) => s.trim())
    .filter(Boolean)
}

// Pack names shipped in packs/ (without .json).
export function availablePacks(dir = PACKS_DIR) {
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.slice(0, -".json".length))
    .sort()
}

function readChecks(env, packs) {
  const v = value(env, "GATE_CHECKS")
  if (v === undefined) return DEFAULT_CHECKS
  const names = list(v, ",")
  if (names.length === 1 && names[0] === "none") return []
  if (names.includes("none"))
    throw new ConfigError("GATE_CHECKS: none cannot be combined with packs")
  for (const n of names) {
    if (!packs.includes(n))
      throw new ConfigError(
        `GATE_CHECKS: unknown pack "${n}" (available: ${packs.join(", ")})`,
      )
  }
  return [...new Set(names)]
}

// env → { enabled, packs, rulesFiles, disableRules, envGuard, strict, log }.
// `packs` are full pack names in load order (`base` first) or [] for none.
// Relative paths (rules files, log) resolve against the project (paths.mjs);
// `cwd` only matters when CLAUDE_PROJECT_DIR is unset.
export function readConfig(
  env = process.env,
  { packs = availablePacks(), cwd = process.cwd() } = {},
) {
  const path = (p) => projectPath(p, env, cwd)
  const enabled = flag(env, "GATE_ENABLED", true)
  const envGuard = flag(env, "GATE_ENV_GUARD", true)
  const strict = flag(env, "GATE_STRICT", false)
  const logValue = value(env, "GATE_LOG")
  const log = logValue === undefined ? null : path(logValue)

  // GATE_RULES (deprecated): one rules file replacing every pack.
  const legacy = value(env, "GATE_RULES")
  let checks, rulesFiles
  if (legacy !== undefined) {
    if (value(env, "GATE_CHECKS") !== undefined || value(env, "GATE_RULES_FILE") !== undefined)
      throw new ConfigError(
        "GATE_RULES cannot be combined with GATE_CHECKS or GATE_RULES_FILE (use GATE_CHECKS=none GATE_RULES_FILE=…)",
      )
    checks = []
    rulesFiles = [path(legacy)]
  } else {
    checks = readChecks(env, packs)
    const files = value(env, "GATE_RULES_FILE")
    rulesFiles = files === undefined ? [] : list(files, ":").map(path)
  }
  const packNames = checks.length ? ["base", ...checks.filter((c) => c !== "base")] : []
  if (!packNames.length && !rulesFiles.length)
    throw new ConfigError("GATE_CHECKS=none needs GATE_RULES_FILE")

  const disabled = value(env, "GATE_DISABLE_RULES")
  const disableRules = disabled === undefined ? [] : [...new Set(list(disabled, ","))]

  return { enabled, packs: packNames, rulesFiles, disableRules, envGuard, strict, log }
}

// Loads the packs and extra files of `config`, drops disabled rules and returns
// parsed rules. Throws RulesError (bad files) or ConfigError (unknown rule id).
export function buildRules(config) {
  const raw = composeRules([...config.packs.map(packPath), ...config.rulesFiles])
  if (config.disableRules.length) {
    const rules = Array.isArray(raw.rules) ? raw.rules : []
    const ids = new Set(rules.map((r) => r?.id))
    const unknown = config.disableRules.filter((id) => !ids.has(id))
    if (unknown.length)
      throw new ConfigError(`GATE_DISABLE_RULES: unknown rule id ${unknown.map((u) => `"${u}"`).join(", ")}`)
    const drop = new Set(config.disableRules)
    raw.rules = rules.filter((r) => !drop.has(r?.id))
  }
  return parseRules(raw)
}

export { RulesError }
export { projectDir, projectPath } from "./paths.mjs"
