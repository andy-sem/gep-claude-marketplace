#!/usr/bin/env node
// Tool-agnostic approval gate engine for Claude Code PreToolUse hooks.
// Reads rules from JSON rule packs (packs/*.json) or the file named by
// GATE_RULES; this file knows no concrete tool names.
// Fails closed: anything it cannot parse or load results in an `ask`.

import { readFileSync, realpathSync, writeFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

export class RulesError extends Error {
  constructor(message) {
    super(message)
    this.name = "RulesError"
  }
}

export class UnparsableError extends Error {
  constructor(message) {
    super(message)
    this.name = "UnparsableError"
  }
}

export const PACKS_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "packs",
)
export const DEFAULT_PACKS = ["base", "postgres", "terraform"]
export const packPath = (name) => join(PACKS_DIR, `${name}.json`)

const MAX_DEPTH = 8
// Placeholder left in a word where a command substitution was (its value is unknown).
const DYN = "\u0000"
const SHELLS = new Set(["bash", "sh", "zsh"])
const ASSIGNMENT_RE = /^[A-Za-z_][A-Za-z0-9_]*=/
// Shell keywords/grouping words that may precede a command.
const LEADING_RESERVED = new Set([
  "if",
  "then",
  "else",
  "elif",
  "fi",
  "do",
  "done",
  "while",
  "until",
  "esac",
  "!",
  "{",
  "}",
])
// Wrapper options that take a value (given separately, attached, or as `--opt=v`).
// Only options that always take a value are listed: wrongly consuming a word could
// hide the real program, so ambiguous ones are left out (the later-token scan in
// evalTokens is the backstop when a value is consumed anyway).
const WRAPPER_VALUE_OPTS = {
  sudo: [
    "-u",
    "-g",
    "-h",
    "-p",
    "-C",
    "-D",
    "-R",
    "-T",
    "-U",
    "-r",
    "-t",
    "--user",
    "--group",
    "--host",
    "--prompt",
    "--close-from",
    "--chdir",
    "--role",
    "--type",
    "--other-user",
    "--command-timeout",
  ],
  doas: ["-u", "-C"],
  env: ["-u", "-C", "-S", "--unset", "--chdir", "--split-string"],
  timeout: ["-s", "-k", "--signal", "--kill-after"],
  time: ["-f", "-o", "--format", "--output"],
  exec: ["-a"],
  nice: ["-n", "--adjustment"],
  watch: ["-n", "--interval"],
  caffeinate: ["-t", "-w"],
  stdbuf: ["-i", "-o", "-e", "--input", "--output", "--error"],
  ionice: ["-c", "-n", "-p", "-P", "-u", "--class", "--classdata"],
  xargs: [
    "-n",
    "-L",
    "-P",
    "-I",
    "-d",
    "-E",
    "-s",
    "-a",
    "--max-args",
    "--max-lines",
    "--max-procs",
    "--delimiter",
    "--eof",
    "--arg-file",
    "--max-chars",
    "--process-slot-var",
  ],
}

const KNOWN_KINDS = new Set([
  "cli-allowlist",
  "cli-gated",
  "mcp-allowlist",
  "mcp-as-cli",
])

// ---------------------------------------------------------------------------
// Rules loading
// ---------------------------------------------------------------------------

function strArray(value, what) {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.some((v) => typeof v !== "string")) {
    throw new RulesError(`${what} must be an array of strings`)
  }
  return value
}

function nonEmptyStrArray(value, what) {
  const list = strArray(value, what)
  if (list.some((v) => v === "")) {
    throw new RulesError(`${what} must not contain empty strings`)
  }
  return list
}

function strArrayArray(value, what) {
  if (value === undefined) return []
  if (
    !Array.isArray(value) ||
    value.some((v) => !Array.isArray(v) || v.some((s) => typeof s !== "string"))
  ) {
    throw new RulesError(`${what} must be an array of string arrays`)
  }
  return value
}

// A map of program -> flags; every flag must be a non-empty string.
function flagMap(value, what) {
  if (value === undefined) return {}
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new RulesError(`${what} must be an object of string arrays`)
  }
  const out = {}
  for (const [program, flags] of Object.entries(value)) {
    if (
      !Array.isArray(flags) ||
      flags.some((f) => typeof f !== "string" || f === "")
    ) {
      throw new RulesError(
        `${what} ${program} must be an array of non-empty strings`,
      )
    }
    out[program] = flags
  }
  return out
}

function bool(value, what) {
  if (value === undefined) return false
  if (typeof value !== "boolean")
    throw new RulesError(`${what} must be a boolean`)
  return value
}

// Runners run another program: `{ program, valueOptions, subcommands, shellOptions,
// bareBin }`. The legacy form `["pnpm", "exec"]` / `["npx"]` is also accepted.
function runnerList(value) {
  if (value === undefined) return []
  if (!Array.isArray(value)) throw new RulesError("runners must be an array")
  const byProgram = new Map()
  const entry = (program) => {
    if (!byProgram.has(program)) {
      byProgram.set(program, {
        program,
        valueOptions: [],
        subcommands: [],
        shellOptions: [],
        bareBin: false,
      })
    }
    return byProgram.get(program)
  }
  value.forEach((raw, index) => {
    const where = `runner #${index}`
    if (Array.isArray(raw)) {
      if (
        raw.length < 1 ||
        raw.length > 2 ||
        raw.some((v) => typeof v !== "string" || !v)
      ) {
        throw new RulesError(
          `${where} must be ["program"] or ["program", "sub"]`,
        )
      }
      const r = entry(raw[0])
      if (raw.length === 1) r.bareBin = true
      else r.subcommands.push(raw[1])
      return
    }
    if (
      raw === null ||
      typeof raw !== "object" ||
      typeof raw.program !== "string" ||
      !raw.program
    ) {
      throw new RulesError(`${where} needs a string program`)
    }
    const r = entry(raw.program)
    r.valueOptions.push(...strArray(raw.valueOptions, `${where} valueOptions`))
    r.subcommands.push(...strArray(raw.subcommands, `${where} subcommands`))
    r.shellOptions.push(...strArray(raw.shellOptions, `${where} shellOptions`))
    r.bareBin = r.bareBin || bool(raw.bareBin, `${where} bareBin`)
  })
  return [...byProgram.values()]
}

function regex(source, what) {
  if (typeof source !== "string")
    throw new RulesError(`${what} must be a regex string`)
  try {
    return new RegExp(source)
  } catch (e) {
    throw new RulesError(`${what} is not a valid regex: ${e.message}`)
  }
}

function readRulesJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"))
  } catch (e) {
    throw new RulesError(`cannot read rules file ${path}: ${e.message}`)
  }
}

export function loadRules(path) {
  return parseRules(readRulesJson(path))
}

// Merges several raw rules files (packs) into one raw object: string lists are
// concatenated without duplicates, runners/rules are concatenated, and
// inertUnsafeFlags lists are merged per program. Duplicate rule ids are an error.
export function composeRules(paths) {
  const merged = {}
  const ids = new Set()
  for (const path of paths) {
    const raw = readRulesJson(path)
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
      throw new RulesError(`rules file ${path} must contain a JSON object`)
    }
    for (const [key, value] of Object.entries(raw)) {
      if (key === "inertUnsafeFlags") {
        if (value === null || typeof value !== "object" || Array.isArray(value))
          throw new RulesError(`${path}: inertUnsafeFlags must be an object`)
        const into = (merged.inertUnsafeFlags ??= {})
        for (const [prog, flags] of Object.entries(value)) {
          if (!Array.isArray(flags))
            throw new RulesError(`${path}: inertUnsafeFlags.${prog} must be an array`)
          into[prog] = [...new Set([...(into[prog] ?? []), ...flags])]
        }
      } else if (Array.isArray(value)) {
        if (key === "rules") {
          for (const r of value) {
            if (r && typeof r.id === "string") {
              if (ids.has(r.id))
                throw new RulesError(`${path}: duplicate rule id "${r.id}"`)
              ids.add(r.id)
            }
          }
        }
        const prev = merged[key] ?? []
        if (!Array.isArray(prev))
          throw new RulesError(`${path}: ${key} must be an array`)
        merged[key] = value.every((v) => typeof v === "string")
          ? [...new Set([...prev, ...value])]
          : [...prev, ...value]
      } else if (merged[key] === undefined) {
        merged[key] = value
      } else {
        throw new RulesError(`${path}: ${key} is set by more than one pack`)
      }
    }
  }
  return merged
}

export function loadPacks(paths) {
  return parseRules(composeRules(paths))
}

export function parseRules(parsed) {
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new RulesError("rules file must contain a JSON object")
  }
  if (parsed.rules !== undefined && !Array.isArray(parsed.rules)) {
    throw new RulesError("rules must be an array")
  }
  const rules = (parsed.rules ?? []).map((raw, index) => {
    if (
      raw === null ||
      typeof raw !== "object" ||
      typeof raw.id !== "string" ||
      !raw.id
    ) {
      throw new RulesError(`rule #${index} needs a string id`)
    }
    const where = `rule "${raw.id}"`
    if (!KNOWN_KINDS.has(raw.kind)) {
      throw new RulesError(`${where} has unknown kind "${raw.kind}"`)
    }
    const rule = { id: raw.id, kind: raw.kind }
    switch (raw.kind) {
      case "cli-allowlist":
        rule.programs = strArray(raw.programs, `${where} programs`)
        rule.skipWords = strArray(raw.skipWords, `${where} skipWords`)
        rule.readPrefixes = strArrayArray(
          raw.readPrefixes,
          `${where} readPrefixes`,
        )
        rule.readSequences = strArrayArray(
          raw.readSequences,
          `${where} readSequences`,
        )
        rule.readVerbs = strArray(raw.readVerbs, `${where} readVerbs`)
        rule.writeVerbs = strArray(raw.writeVerbs, `${where} writeVerbs`)
        rule.helpFlags = strArray(raw.helpFlags, `${where} helpFlags`)
        rule.helpWords = strArray(raw.helpWords, `${where} helpWords`)
        break
      case "cli-gated":
        rule.programs = strArray(raw.programs, `${where} programs`)
        rule.gatedPrefixes = strArrayArray(
          raw.gatedPrefixes,
          `${where} gatedPrefixes`,
        )
        rule.unlessFlags = strArray(raw.unlessFlags, `${where} unlessFlags`)
        rule.helpFlags = strArray(raw.helpFlags, `${where} helpFlags`)
        rule.helpWords = strArray(raw.helpWords, `${where} helpWords`)
        break
      case "mcp-allowlist":
        rule.tool = regex(raw.tool, `${where} tool`)
        rule.readTools = strArray(raw.readTools, `${where} readTools`).map(
          (r) => regex(r, `${where} readTools entry`),
        )
        break
      case "mcp-as-cli":
        rule.tool = regex(raw.tool, `${where} tool`)
        if (
          typeof raw.argsField !== "string" ||
          typeof raw.program !== "string"
        ) {
          throw new RulesError(`${where} needs string argsField and program`)
        }
        rule.argsField = raw.argsField
        rule.program = raw.program
        break
    }
    return rule
  })
  return {
    wrappers: strArray(parsed.wrappers, "wrappers"),
    runners: runnerList(parsed.runners),
    inertPrograms: strArray(parsed.inertPrograms, "inertPrograms"),
    inertUnsafeFlags: flagMap(parsed.inertUnsafeFlags, "inertUnsafeFlags"),
    scriptPatterns: strArray(parsed.scriptPatterns, "scriptPatterns").map(
      (source) => regex(source, "scriptPatterns entry"),
    ),
    scriptScanExempt: nonEmptyStrArray(
      parsed.scriptScanExempt,
      "scriptScanExempt",
    ),
    rules,
  }
}

// ---------------------------------------------------------------------------
// Shell tokenizer
// ---------------------------------------------------------------------------

function basename(token) {
  return token.split("/").pop()
}

// Scans `s` from `start`, pushing every simple command found (including those in
// nested substitutions and groups) onto `out`. When `closer` is ')' it stops after
// the matching paren and returns the index following it; otherwise it scans to the end.
function scanList(s, start, closer, out, depth) {
  const scope = { parent: currentScope }
  currentScope = scope
  try {
    return scanListInner(s, start, closer, out, depth, scope)
  } finally {
    currentScope = scope.parent
  }
}

// The list being scanned, so that every command can say which `( … )` group or
// substitution it belongs to (`cmd.scope`, with a `parent` chain). A `cd` inside a
// scope does not move the directory of its parent.
let currentScope = null

function scanListInner(s, start, closer, out, depth, scope) {
  if (depth > MAX_DEPTH) throw new UnparsableError("nesting too deep")
  let i = start
  let tokens = []
  let word = ""
  let inWord = false
  let wordQuoted = false
  let redirNext = false
  let heredocPending = null
  let herePending = false
  let cmdStdin = []
  const heredocs = []

  const endWord = () => {
    if (!inWord) return
    if (redirNext) {
      redirNext = false
      if (heredocPending) {
        const entry = {
          delim: word,
          quoted: wordQuoted,
          strip: heredocPending.strip,
          body: "",
        }
        heredocs.push(entry)
        cmdStdin.push(entry)
        heredocPending = null
      } else if (herePending) {
        cmdStdin.push({ body: word })
        herePending = false
      }
    } else {
      tokens.push(word)
    }
    word = ""
    inWord = false
    wordQuoted = false
  }
  const endCmd = () => {
    endWord()
    redirNext = false
    heredocPending = null
    herePending = false
    let k = 0
    while (k < tokens.length && LEADING_RESERVED.has(tokens[k])) k++
    const cmd = tokens.slice(k)
    if (cmd.length) {
      // heredoc / here-string payloads fed to this command (not enumerable)
      Object.defineProperty(cmd, "stdin", { value: cmdStdin })
      Object.defineProperty(cmd, "scope", { value: scope })
      out.push(cmd)
    }
    cmdStdin = []
    tokens = []
  }
  const append = (text) => {
    word += text
    inWord = true
  }
  const sub = (from) => {
    word += DYN
    return scanList(s, from, ")", out, depth + 1)
  }
  const backtick = (from) => {
    word += DYN
    const end = findBacktickEnd(s, from)
    const inner = s.slice(from + 1, end).replace(/\\([`$\\])/g, "$1")
    scanList(inner, 0, null, out, depth + 1)
    return end + 1
  }
  const redirect = (op) => {
    if (inWord && !wordQuoted && /^\d+$/.test(word)) {
      word = ""
      inWord = false
    } else {
      endWord()
    }
    if (s[i + op.length] === "(") return // process substitution, handled as a group
    redirNext = true
    if (op === "<<" || op === "<<-") heredocPending = { strip: op === "<<-" }
    else if (op === "<<<") herePending = true
  }
  const consumeHeredocs = () => {
    for (const h of heredocs) {
      const lines = []
      let found = false
      while (i < s.length && !found) {
        let nl = s.indexOf("\n", i)
        if (nl === -1) nl = s.length
        const line = s.slice(i, nl)
        i = Math.min(nl + 1, s.length)
        const cmp = h.strip ? line.replace(/^\t+/, "") : line
        if (cmp === h.delim) found = true
        else lines.push(line)
      }
      h.body = lines.join("\n")
      if (!h.quoted) extractSubs(h.body, out, depth + 1)
    }
    heredocs.length = 0
  }

  while (i < s.length) {
    const c = s[i]
    if (c === "\\") {
      if (i + 1 < s.length) {
        if (s[i + 1] !== "\n") append(s[i + 1])
        i += 2
      } else {
        i++
      }
    } else if (c === "'") {
      const end = s.indexOf("'", i + 1)
      if (end === -1) throw new UnparsableError("unterminated single quote")
      append(s.slice(i + 1, end))
      wordQuoted = true
      i = end + 1
    } else if (c === '"') {
      inWord = true
      wordQuoted = true
      i++
      let closed = false
      while (i < s.length) {
        const d = s[i]
        if (d === '"') {
          closed = true
          i++
          break
        } else if (d === "\\" && i + 1 < s.length) {
          if (s[i + 1] !== "\n") word += s[i + 1]
          i += 2
        } else if (d === "$" && s[i + 1] === "(") {
          i = sub(i + 2)
        } else if (d === "$" && s[i + 1] === "{") {
          const end = findBraceEnd(s, i + 2, out, depth)
          word += s.slice(i, end)
          i = end
        } else if (d === "`") {
          i = backtick(i)
        } else {
          word += d
          i++
        }
      }
      if (!closed) throw new UnparsableError("unterminated double quote")
    } else if (c === "$" && s[i + 1] === "(") {
      inWord = true
      i = sub(i + 2)
    } else if (c === "$" && s[i + 1] === "{") {
      const end = findBraceEnd(s, i + 2, out, depth)
      append(s.slice(i, end))
      i = end
    } else if (c === "`") {
      inWord = true
      i = backtick(i)
    } else if (c === " " || c === "\t" || c === "\r") {
      endWord()
      i++
    } else if (c === "\n") {
      endCmd()
      i++
      consumeHeredocs()
    } else if (c === "#" && !inWord) {
      while (i < s.length && s[i] !== "\n") i++
    } else if (c === ";") {
      endCmd()
      i++
    } else if (c === "|") {
      endCmd()
      i += s[i + 1] === "|" || s[i + 1] === "&" ? 2 : 1
    } else if (c === "&") {
      if (s[i + 1] === "&") {
        endCmd()
        i += 2
      } else if (s[i + 1] === ">") {
        const op = s[i + 2] === ">" ? "&>>" : "&>"
        redirect(op)
        i += op.length
      } else {
        endCmd()
        i++
      }
    } else if (c === "<" || c === ">") {
      const m = /^(?:<<<|<<-|<<|<>|>>|>\||>&|<&|>|<)/.exec(s.slice(i, i + 3))
      redirect(m[0])
      i += m[0].length
    } else if (c === "(") {
      endCmd()
      i = scanList(s, i + 1, ")", out, depth + 1)
    } else if (c === ")") {
      if (closer === ")") {
        endCmd()
        return i + 1
      }
      throw new UnparsableError("unbalanced parenthesis")
    } else {
      append(c)
      i++
    }
  }
  if (closer !== null)
    throw new UnparsableError("unterminated command substitution or group")
  endCmd()
  return i
}

function findBacktickEnd(s, from) {
  for (let j = from + 1; j < s.length; j++) {
    if (s[j] === "\\") j++
    else if (s[j] === "`") return j
  }
  throw new UnparsableError("unterminated backtick substitution")
}

// Returns the index after the closing `}` of a `${…}` expansion starting at `from`
// (the index after `${`), scanning any command substitutions inside it.
function findBraceEnd(s, from, out, depth) {
  let level = 1
  let j = from
  while (j < s.length) {
    const c = s[j]
    if (c === "\\") {
      j += 2
    } else if (c === "$" && s[j + 1] === "(") {
      j = scanList(s, j + 2, ")", out, depth + 1)
    } else if (c === "`") {
      const end = findBacktickEnd(s, j)
      scanList(s.slice(j + 1, end), 0, null, out, depth + 1)
      j = end + 1
    } else if (c === "'" || c === '"') {
      const end = s.indexOf(c, j + 1)
      if (end === -1)
        throw new UnparsableError("unterminated quote in parameter expansion")
      j = end + 1
    } else if (c === "{") {
      level++
      j++
    } else if (c === "}") {
      level--
      j++
      if (level === 0) return j
    } else {
      j++
    }
  }
  throw new UnparsableError("unterminated parameter expansion")
}

// Finds command substitutions inside text that is otherwise literal (heredoc bodies).
function extractSubs(text, out, depth) {
  let j = 0
  while (j < text.length) {
    const c = text[j]
    if (c === "\\") j += 2
    else if (c === "$" && text[j + 1] === "(")
      j = scanList(text, j + 2, ")", out, depth + 1)
    else if (c === "`") {
      const end = findBacktickEnd(text, j)
      scanList(text.slice(j + 1, end), 0, null, out, depth + 1)
      j = end + 1
    } else j++
  }
}

// Reads a shell invocation's options: `-c <str>`, option values (`-o`, `-O`), and
// whether a script file argument follows (otherwise the shell reads stdin).
function parseShell(tokens) {
  let stdinFlag = false
  let hasC = false
  for (let j = 1; j < tokens.length; j++) {
    const t = tokens[j]
    if (t === "--") {
      if (hasC) return { command: tokens[j + 1] ?? "" }
      return { script: j + 1 < tokens.length && !stdinFlag, index: j + 1 }
    }
    if (t === "-") {
      stdinFlag = true // a lone `-` makes the shell read stdin
      continue
    }
    if (!/^[-+]/.test(t)) {
      if (hasC) return { command: t } // first operand after -c is the command string
      return { script: !stdinFlag, index: j }
    }
    if (/^-[A-Za-z]*c[A-Za-z]*$/.test(t)) hasC = true
    if (/^-[A-Za-z]*s[A-Za-z]*$/.test(t)) stdinFlag = true
    // Option values: a short-flag cluster ending in o/O (`-eo`, `-lo`, `+O`) or a long option
    if (
      /^[-+][A-Za-z]*[oO]$/.test(t) ||
      ["--rcfile", "--init-file"].includes(t)
    )
      j++
  }
  return hasC ? { command: "" } : { script: false }
}

// Strings that a command hands to a nested shell: `<sh> -c '<str>'`, `eval …` and
// heredoc / here-string payloads fed to a shell. A shell that reads an unknown stdin,
// or a string containing an unresolvable `$` expansion, cannot be analysed.
function nestedStrings(rawTokens) {
  let k = 0
  while (k < rawTokens.length && ASSIGNMENT_RE.test(rawTokens[k])) k++
  const tokens = rawTokens.slice(k)
  if (!tokens.length) return []
  const base = basename(tokens[0])
  let found = []
  if (base === "eval") {
    found = tokens.length > 1 ? [tokens.slice(1).join(" ")] : []
  } else if (SHELLS.has(base)) {
    const info = parseShell(tokens)
    if (info.command !== undefined) {
      found = info.command ? [info.command] : []
    } else if (!info.script) {
      found = (rawTokens.stdin ?? []).map((e) => e.body)
      if (!found.length) throw new UnparsableError("shell reads stdin")
    }
  }
  for (const str of found) {
    if (/\$(?!\()/.test(str)) throw new UnparsableError("dynamic shell command")
  }
  return found
}

function splitInner(cmd, depth) {
  if (depth > MAX_DEPTH) throw new UnparsableError("nesting too deep")
  const out = []
  scanList(cmd, 0, null, out, depth)
  const result = [...out]
  for (const tokens of out) {
    for (const str of nestedStrings(tokens)) {
      const inner = splitInner(str, depth + 1)
      // the outermost scope of the string remembers the command that ran the shell
      for (const cmd of inner) {
        let top = cmd.scope
        while (top?.parent) top = top.parent
        if (top && !top.host) top.host = tokens
      }
      result.push(...inner)
    }
  }
  return result
}

export function splitCommand(cmd) {
  return splitInner(cmd, 0)
}

// ---------------------------------------------------------------------------
// Normalization and rule evaluation
// ---------------------------------------------------------------------------

// Strips leading options from `tokens`. Options in `valueOpts` take a value (given
// separately, attached to a short option, or as `--opt=value`); short options may be
// clustered (`-iu root`). An option in `shellOpts` makes the remaining words a shell
// command string, returned as `shell`.
function stripOptions(tokens, valueOpts = [], shellOpts = []) {
  const seen = []
  const values = {}
  let k = 0
  while (k < tokens.length) {
    const tok = tokens[k]
    if (!tok.startsWith("-") || tok === "-") break
    k++
    if (tok === "--") break
    if (tok.startsWith("--")) {
      const eq = tok.indexOf("=")
      const name = eq === -1 ? tok : tok.slice(0, eq)
      seen.push(name)
      if (shellOpts.includes(name)) {
        const words =
          eq === -1 ? tokens.slice(k) : [tok.slice(eq + 1), ...tokens.slice(k)]
        return { rest: [], seen, values, shell: words.join(" ") }
      }
      if (eq !== -1) {
        values[name] = tok.slice(eq + 1)
      } else if (valueOpts.includes(name)) {
        values[name] = tokens[k]
        k++
      }
      continue
    }
    for (let c = 1; c < tok.length; c++) {
      const name = `-${tok[c]}`
      const attached = tok.slice(c + 1)
      seen.push(name)
      if (shellOpts.includes(name)) {
        const words = attached
          ? [attached, ...tokens.slice(k)]
          : tokens.slice(k)
        return { rest: [], seen, values, shell: words.join(" ") }
      }
      if (valueOpts.includes(name)) {
        if (attached) {
          values[name] = attached
        } else {
          values[name] = tokens[k]
          k++
        }
        break
      }
    }
  }
  return { rest: tokens.slice(k), seen, values }
}

// Words of an `env -S` string (no expansions allowed: their value is unknown).
function splitWords(str) {
  if (str.includes("$") || str.includes("`")) {
    throw new UnparsableError("dynamic env -S string")
  }
  const out = []
  scanList(str, 0, null, out, MAX_DEPTH)
  return out.flat()
}

// `tool@1.2.3` / `@scope/pkg@latest` -> the bin name without its version.
function stripVersion(token) {
  const m = /^(@?[^@]+)@[^/]*$/.exec(token)
  return m ? m[1] : token
}

// Drops leading assignments and wrappers (`sudo`, `env`, …) off a simple command and
// stops at anything else, runners included. `argsFromInput` is set when a wrapper
// supplies extra arguments (`xargs`), so the real argument list is unknown. `final`
// is set when the wrapper turned the rest into a shell command (`watch`).
export function stripWrappers(rawTokens, rules) {
  let tokens = rawTokens
  let argsFromInput = false
  for (let guard = 0; guard < 64; guard++) {
    let k = 0
    while (k < tokens.length && ASSIGNMENT_RE.test(tokens[k])) k++
    tokens = tokens.slice(k)
    if (!tokens.length) return { tokens, argsFromInput }
    const base = basename(tokens[0])
    if (!rules.wrappers.includes(base)) return { tokens, argsFromInput }
    const opts = stripOptions(tokens.slice(1), WRAPPER_VALUE_OPTS[base] ?? [])
    let rest = opts.rest
    if (base === "env") {
      const split = opts.values["-S"] ?? opts.values["--split-string"]
      if (split !== undefined) rest = [...splitWords(split), ...rest]
    } else if (base === "timeout") {
      rest = rest.slice(1) // duration
    } else if (base === "xargs") {
      argsFromInput = true
    } else if (
      base === "watch" &&
      !opts.seen.includes("-x") &&
      !opts.seen.includes("--exec")
    ) {
      // watch hands its joined arguments to `sh -c`
      const cmd = rest.length ? ["sh", "-c", rest.join(" ")] : []
      return { tokens: cmd, argsFromInput, final: true }
    }
    tokens = rest
  }
  throw new UnparsableError("wrapper nesting too deep")
}

// The index of the script operand of `bash|sh|zsh …`, or -1 when the shell runs a
// `-c` string or reads stdin.
export function shellScriptIndex(tokens) {
  if (!tokens.length || !SHELLS.has(basename(tokens[0]))) return -1
  const info = parseShell(tokens)
  return info.script ? info.index : -1
}

// The shell command string a simple command hands to a shell through wrappers and
// runners (`watch bash x.sh`, `timeout 5 bash -c '…'`, `npx -c '…'`), or null. A plain
// `bash -c '…'` is also found by `splitCommand`; a string with an unresolvable `$`
// expansion cannot be analysed and gives null.
export function nestedShellString(rawTokens, rules) {
  let n
  try {
    n = normalize(rawTokens, rules)
  } catch {
    return null
  }
  if (!n.tokens.length || !SHELLS.has(basename(n.tokens[0]))) return null
  const str = parseShell(n.tokens).command
  if (!str || /\$(?!\()/.test(str)) return null
  return str
}

// Peels wrappers and runners (`npx`, `pnpm exec`, …) off a simple command.
function normalize(rawTokens, rules) {
  let tokens = rawTokens
  let argsFromInput = false
  for (let guard = 0; guard < 64; guard++) {
    const w = stripWrappers(tokens, rules)
    tokens = w.tokens
    argsFromInput = argsFromInput || w.argsFromInput
    if (w.final || !tokens.length) return { tokens, argsFromInput }
    const base = basename(tokens[0])
    const runner = rules.runners.find((r) => r.program === base)
    if (runner) {
      const strip = (list) =>
        stripOptions(list, runner.valueOptions, runner.shellOptions)
      let opts = strip(tokens.slice(1))
      if (
        opts.shell === undefined &&
        opts.rest.length &&
        runner.subcommands.includes(opts.rest[0])
      ) {
        opts = strip(opts.rest.slice(1))
      } else if (opts.shell === undefined && !runner.bareBin) {
        return { tokens, argsFromInput } // a runner command that runs no bin
      }
      if (opts.shell !== undefined) {
        return { tokens: ["sh", "-c", opts.shell], argsFromInput }
      }
      tokens = opts.rest.length
        ? [stripVersion(opts.rest[0]), ...opts.rest.slice(1)]
        : []
      continue
    }
    return { tokens, argsFromInput }
  }
  throw new UnparsableError("wrapper nesting too deep")
}

function ask(id, detail) {
  return { decision: "ask", reason: `${id}: ${detail}` }
}

// True when `seq` occurs in `list` in order, possibly with other words between
// (flag values sit between subcommand words: `tool --dir x db push`).
function isSubsequence(list, seq) {
  let k = 0
  for (const item of list) {
    if (k < seq.length && item === seq[k]) k++
  }
  return k === seq.length
}

// Read/write decision for an allowlisted program's arguments.
// - Words after a bare flag (`--zone list`, `-o ls`) may be flag values, and words
//   after `--` are passed through: such "loose" words never establish a read, but
//   still count as write verbs.
// - readPrefixes / readSequences are anchored at the first firm word (after any
//   leading skipWords). Write verbs inside the matched command path ask; with a
//   readSequence, words after it are arguments and are ignored; with a readPrefix
//   any write verb asks.
// - Otherwise any write verb asks, a firm read verb passes, and anything else is an
//   unknown subcommand (asked, except in `later` mode where only writes ask).
function allowlistDecision(rule, rest, later) {
  const words = []
  let loose = false
  let passthrough = false
  for (const t of rest) {
    if (!passthrough && t === "--") {
      passthrough = true
      continue
    }
    if (!passthrough && t.length > 1 && t.startsWith("-")) {
      loose = !t.includes("=")
      continue
    }
    words.push({ tok: t, firm: !passthrough && !loose })
    loose = false
  }
  const isWrite = (w) => rule.writeVerbs.includes(w.tok)
  const writeAsk = (w) => ask(rule.id, `write verb "${w.tok}"`)
  const firm = words.map((w, i) => ({ ...w, i })).filter((w) => w.firm)
  let s = 0
  while (s < firm.length && rule.skipWords.includes(firm[s].tok)) s++
  const anchored = (seq) =>
    seq.length > 0 &&
    seq.length <= firm.length - s &&
    seq.every((x, k) => firm[s + k].tok === x)
      ? firm.slice(s, s + seq.length).map((w) => w.i)
      : null
  for (const prefix of rule.readPrefixes) {
    const m = anchored(prefix)
    if (m) {
      const w = words.find((w, i) => !m.includes(i) && isWrite(w))
      return w ? writeAsk(w) : null
    }
  }
  for (const seq of rule.readSequences) {
    const m = anchored(seq)
    if (m) {
      const end = m[m.length - 1]
      const w = words.find((w, i) => i < end && !m.includes(i) && isWrite(w))
      return w ? writeAsk(w) : null
    }
  }
  const w = words.find(isWrite)
  if (w) return writeAsk(w)
  if (later) return null
  if (firm.some((w) => rule.readVerbs.includes(w.tok))) return null
  return ask(rule.id, "unknown subcommand")
}

// `later`: the program was found after the command word (an unknown wrapper such as
// `./with-secrets.sh env tool …`). `argsFromInput`: arguments are appended at
// run time (`xargs`).
function applyCliRule(
  rule,
  tokens,
  { later = false, argsFromInput = false } = {},
) {
  const program = basename(tokens[0])
  const rest = tokens.slice(1)
  const dynamic = argsFromInput || rest.some(isDynamic)
  switch (rule.kind) {
    case "cli-allowlist": {
      if (!rule.programs.includes(program)) return null
      if (isHelpCall(rule, rest)) return null
      if (dynamic) return ask(rule.id, "dynamic argument")
      return allowlistDecision(rule, rest, later)
    }
    case "cli-gated": {
      if (!rule.programs.includes(program)) return null
      if (isHelpCall(rule, rest)) return null
      if (dynamic) return ask(rule.id, "dynamic argument")
      const positionals = rest.filter((t) => !t.startsWith("-"))
      if (!rule.gatedPrefixes.some((p) => isSubsequence(positionals, p)))
        return null
      const exempt = rule.unlessFlags.some((f) =>
        rest.some((t) => t === f || t.startsWith(`${f}=`)),
      )
      return exempt ? null : ask(rule.id, "gated invocation")
    }
    default:
      return null
  }
}

// True when the arguments only ask the program for help, which changes nothing:
// - a `helpFlags` token before any `--`, unless the token before it is a bare flag
//   (`--no-traffic --help`: the help flag could be that flag's value);
// - or the first firm positional word (after `skipWords`) is a `helpWords` entry.
// The flags are configured per rule: `-h` means host for psql and header for some object-storage CLIs.
function isHelpCall(rule, rest) {
  const flags = rule.helpFlags ?? []
  const words = rule.helpWords ?? []
  if (!flags.length && !words.length) return false
  const skip = rule.skipWords ?? []
  let loose = false
  let skipping = true
  for (let i = 0; i < rest.length; i++) {
    const t = rest[i]
    if (t === "--") return false
    if (t.length > 1 && t.startsWith("-")) {
      if (flags.includes(t) && !loose) return true
      loose = !t.includes("=")
      continue
    }
    if (!loose) {
      if (skipping && skip.includes(t)) continue
      if (skipping) {
        if (words.includes(t)) return true
        skipping = false
      }
    }
    loose = false
  }
  return false
}

// A word whose value is only known at run time: `$…` expansions, command
// substitutions, and the `{}` placeholder `find -exec` / `xargs -I{}` fill in.
function isDynamic(token) {
  return token.includes("$") || token.includes(DYN) || token === "{}"
}

// The `-c` string of a shell invocation found later in a command, if any.
function shellCommandString(tokens) {
  const info = parseShell(tokens)
  if (!info.command) return []
  if (/\$(?!\()/.test(info.command))
    throw new UnparsableError("dynamic shell command")
  return [info.command]
}

function askInertFlag() {
  return { decision: "ask", reason: "inert program with command flag" }
}

// True when `args` contain a flag of `program` listed in inertUnsafeFlags.
// Matches the flag itself, `--flag=value`, a joined short value (`-Pcmd`), a
// short flag inside a bundle (`-aPcmd`), a "+" command (`less +!cmd`) and, for
// long flags, an abbreviation (`--pag`) since getopt_long accepts them. It does
// not match a longer option that merely starts with the flag (`--pre-glob`).
function hasUnsafeFlag(program, args, rules) {
  const flags = rules.inertUnsafeFlags[program]
  if (!flags?.length) return false
  return args.some((a) =>
    flags.some((f) => {
      if (f.startsWith("--")) {
        if (!a.startsWith("--")) return false
        const name = a.split("=")[0]
        return name.length > 2 && f.startsWith(name)
      }
      if (f.startsWith("-")) {
        return a.startsWith("-") && !a.startsWith("--") && a.includes(f[1])
      }
      return a.startsWith(f)
    }),
  )
}

// Scans the words after the command word for a rule program, a runner or an
// embedded `<shell> -c` / `eval`, so that unknown wrappers (`./with-secrets.sh f
// tool push`, `script -q /dev/null …`, `find -exec …`) cannot hide a gated
// call. Programs listed in inertPrograms do not run their arguments and are
// skipped, unless an inertUnsafeFlags flag makes them run one (`rg --pre CMD`,
// `man -P CMD`): then the call is not inert and asks without parsing the value.
function laterScan(raw, tokens, rules, depth) {
  if (rules.inertPrograms.includes(basename(tokens[0]))) {
    return hasUnsafeFlag(basename(tokens[0]), tokens.slice(1), rules)
      ? askInertFlag()
      : null
  }
  for (let j = 1; j < raw.length; j++) {
    const t = raw[j]
    if (t.startsWith("-") || t.includes(":") || t.includes("=") || isDynamic(t))
      continue
    const base = basename(t)
    const sub = raw.slice(j)
    if (rules.inertPrograms.includes(base)) {
      // its arguments, up to a `find -exec` terminator (`;` or `{} +`)
      const start = j + 1
      while (
        j + 1 < raw.length &&
        raw[j + 1] !== ";" &&
        !(raw[j + 1] === "+" && raw[j] === "{}")
      )
        j++
      if (hasUnsafeFlag(base, raw.slice(start, j + 1), rules)) {
        return askInertFlag()
      }
      continue
    }
    if (rules.runners.some((r) => r.program === base)) {
      // everything after a runner is the runner's command
      return evalTokens(sub, rules, depth + 1)
    }
    if (SHELLS.has(base) || base === "eval") {
      const strs =
        base === "eval" ? nestedStrings(sub) : shellCommandString(sub)
      for (const str of strs) {
        for (const cmd of splitInner(str, depth + 1)) {
          const r = evalTokens(cmd, rules, depth + 1)
          if (r) return r
        }
      }
      continue
    }
    for (const rule of rules.rules) {
      const r = applyCliRule(rule, sub, { later: true })
      if (r) return r
    }
  }
  return null
}

function evalTokens(rawTokens, rules, depth) {
  if (depth > MAX_DEPTH) throw new UnparsableError("nesting too deep")
  let k = 0
  while (k < rawTokens.length && ASSIGNMENT_RE.test(rawTokens[k])) k++
  const { tokens, argsFromInput } = normalize(rawTokens, rules)
  if (!tokens.length) return null
  tokens.stdin = rawTokens.stdin
  if (tokens[0] === "" || isDynamic(tokens[0]))
    throw new UnparsableError("dynamic command word")

  // A shell/eval hidden behind wrappers; plain ones were already expanded by splitCommand.
  if (nestedStrings(rawTokens).length === 0) {
    for (const str of nestedStrings(tokens)) {
      for (const cmd of splitInner(str, depth + 1)) {
        const r = evalTokens(cmd, rules, depth + 1)
        if (r) return r
      }
    }
  }

  for (const rule of rules.rules) {
    const r = applyCliRule(rule, tokens, { argsFromInput })
    if (r) return r
  }
  return laterScan(rawTokens.slice(k), tokens, rules, depth)
}

function toolSuffixMatch(rule, toolName) {
  return rule.tool.exec(toolName)
}

function evalMcp(rule, input, rules) {
  const m = toolSuffixMatch(rule, input.tool_name)
  if (!m) return null
  if (rule.kind === "mcp-allowlist") {
    const suffix = m[1] ?? ""
    if (rule.readTools.some((re) => re.test(suffix))) return null
    return ask(rule.id, suffix)
  }
  // mcp-as-cli
  const args = input.tool_input?.[rule.argsField]
  if (!Array.isArray(args) || args.some((a) => typeof a !== "string")) {
    return ask(
      "unparsable",
      `${input.tool_name} is missing a string array "${rule.argsField}"`,
    )
  }
  const list =
    args.length && basename(args[0]) === rule.program ? args.slice(1) : args
  return evalTokens(
    [rule.program, ...list],
    { ...rules, rules: rules.rules.filter(isCliRule) },
    0,
  )
}

function isCliRule(rule) {
  return rule.kind === "cli-allowlist" || rule.kind === "cli-gated"
}

export function classify(input, rules) {
  try {
    if (input === null || typeof input !== "object" || Array.isArray(input)) {
      return ask("unparsable", "hook input is not an object")
    }
    const toolName = input.tool_name
    if (typeof toolName !== "string")
      return ask("unparsable", "hook input has no tool_name")

    if (toolName === "Bash") {
      const command = input.tool_input?.command
      if (typeof command !== "string")
        return ask("unparsable", "Bash call has no command")
      try {
        for (const tokens of splitCommand(command)) {
          const r = evalTokens(tokens, rules, 0)
          if (r) return r
        }
      } catch (e) {
        // The command string itself could not be parsed. Marked so the
        // optional Jev layer may judge it; input-level failures stay closed.
        if (e instanceof UnparsableError)
          return { ...ask("unparsable", e.message), commandUnparsable: true }
        throw e
      }
      return null
    }

    for (const rule of rules.rules) {
      if (rule.kind !== "mcp-allowlist" && rule.kind !== "mcp-as-cli") continue
      const r = evalMcp(rule, input, rules)
      if (r) return r
    }
    return null
  } catch (e) {
    if (e instanceof UnparsableError) return ask("unparsable", e.message)
    return ask("unparsable", `internal error: ${e?.message ?? e}`)
  }
}

// ---------------------------------------------------------------------------
// CLI entry
// ---------------------------------------------------------------------------

function emit(result) {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: result.decision,
        permissionDecisionReason: result.reason,
      },
    }),
  )
}

// Optional Jev layer (gate-jev.mjs), loaded only when GATE_JEV is set so the
// output is unchanged without it. With Jev on, every Bash command and every MCP
// call (any server) is sent; Read, Edit, Write, Glob and Grep are not. gate-config
// answers and input-level unparsable answers (bad JSON, no tool name, no command,
// an MCP call missing its args) are never touched; a Bash command string the
// parser could not read is sent to Jev, falling back to the unparsable ask when
// Jev fails or is unsure. A missing or invalid Jev variable asks. Whatever the rules
// said stays the answer when Jev fails or is unsure.
async function applyJev(input, result, rules, collected, env = process.env) {
  if (!env.GATE_JEV) return result
  if (result && /^gate-config:/.test(result.reason)) return result
  if (result && /^unparsable:/.test(result.reason) && !result.commandUnparsable)
    return result
  let jev, cfg
  try {
    jev = await import("./gate-jev.mjs")
    cfg = jev.readJevConfig(env)
  } catch (e) {
    return ask("gate-config", e?.message ?? String(e))
  }
  if (!cfg) return result
  const tool = input?.tool_name
  let call
  if (tool === "Bash") {
    call = {
      tool,
      command: input.tool_input.command,
      scripts: collected?.files ?? [],
      problems: collected?.problems ?? [],
    }
  } else if (typeof tool === "string" && tool.startsWith("mcp__")) {
    call = { tool, input: input.tool_input ?? {} }
  } else {
    return result
  }
  try {
    return await jev.runJev(call, result, cfg)
  } catch {
    return result
  }
}

// The full decision for one hook input: the rule result, the script scan as a
// fallback for Bash calls no rule matched, then the optional Jev layer. Returns an
// `ask` result or null (no output).
export async function gate(input, rules, { env = process.env, cwd } = {}) {
  let result = classify(input, rules)
  let collected = null
  const command = input?.tool_input?.command
  const closed =
    result &&
    (/^gate-config:/.test(result.reason) ||
      (/^unparsable:/.test(result.reason) && !result.commandUnparsable))
  if (
    input?.tool_name === "Bash" &&
    typeof command === "string" &&
    !closed &&
    (!result || env.GATE_JEV)
  ) {
    try {
      const scripts = await import("./gate-scripts.mjs")
      const where =
        typeof input.cwd === "string" ? input.cwd : (cwd ?? process.cwd())
      collected = scripts.collectScripts(command, rules, {
        cwd: where,
        root: scripts.findProjectRoot(where, env),
      })
      if (!result) result = scripts.scanScripts(collected, rules)
    } catch (e) {
      return ask("gate-config", `script scan failed: ${e?.message ?? e}`)
    }
  }
  return applyJev(input, result, rules, collected, env)
}

async function main() {
  let result
  try {
    let rules
    try {
      // WP-G1: GATE_RULES names one rules file; otherwise the packs ported from
      // the source ruleset are loaded. Env-driven pack selection (GATE_CHECKS)
      // replaces this in WP-G3.
      rules = process.env.GATE_RULES
        ? loadRules(process.env.GATE_RULES)
        : loadPacks(DEFAULT_PACKS.map(packPath))
    } catch (e) {
      if (e instanceof RulesError) result = ask("gate-config", e.message)
      else throw e
    }
    if (!result) {
      let input
      try {
        input = JSON.parse(readFileSync(0, "utf8"))
      } catch {
        input = undefined
      }
      if (input === undefined) {
        result = ask("unparsable", "hook input is not valid JSON")
      } else {
        result = await gate(input, rules)
      }
    }
  } catch (e) {
    result = ask("gate-config", `internal error: ${e?.message ?? e}`)
  }
  if (result) emit(result)
  // Tell the wrapper the engine ran to completion (allow = empty stdout).
  if (process.env.GATE_DONE_FILE) {
    try {
      writeFileSync(process.env.GATE_DONE_FILE, "done")
    } catch {}
  }
  process.exit(0)
}

function isMain() {
  if (process.env.GATE_RUN === "1") return true
  try {
    return (
      realpathSync(process.argv[1]) ===
      realpathSync(fileURLToPath(import.meta.url))
    )
  } catch {
    return false
  }
}

if (isMain()) main()
