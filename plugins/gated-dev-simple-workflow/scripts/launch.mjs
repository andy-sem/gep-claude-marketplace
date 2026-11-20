#!/usr/bin/env node
// Opens one Claude Code session per ticket, running `/ticket <KEY>`, in a new
// Orca or iTerm2 tab. File-based: tickets are `<ticketsDir>/<KEY>/ticket.md`.
//
//   node launch.mjs [--dry-run] [--remote-control] KEY...
//   node launch.mjs [--dry-run] [--remote-control] --all
//
// A ticket with a run (a worktree on a `<KEY>/*` branch) is reopened in that
// worktree with `--resume` (for a finished run, `stage: done`, that restarts
// the PR watch, which also cleans up after a merge). A new
// ticket gets its own Orca worktree when the host is Orca and the repo is
// registered there; otherwise the session starts in the main checkout and the
// skill creates the worktree.

import { execFile } from "node:child_process"
import * as nodeFs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const DEFAULT_KEY_PATTERN = "^[A-Za-z][A-Za-z0-9._-]*$"
// Whatever keyPattern says, a key is put into shell commands unquoted.
const SAFE_KEY = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
const SAFE_REF = /^[A-Za-z0-9][A-Za-z0-9._/-]*$/
const CONFIG_KEYS = new Set([
  "ticketsDir",
  "keyPattern",
  "baseBranch",
  "setupCommand",
  "formatCommand",
  "riskPaths",
  "escalationExtra",
  "models",
])
const ALLOWED_ARGS = new Set(["--resume"])
const MAX_SHORT = 40

// ---------------------------------------------------------------------------
// Names and commands
// ---------------------------------------------------------------------------

/** POSIX single-quote escaping. */
export function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`
}

/** Escape a string for use inside an AppleScript double-quoted literal. */
export function appleScriptString(value) {
  return `"${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`
}

/** True when `key` is usable in commands, branch and file names. */
export function isSafeKey(key) {
  return typeof key === "string" && SAFE_KEY.test(key) && !key.includes("..")
}

/**
 * A ticket title reduced to a safe, short phrase: every character outside
 * `[A-Za-z0-9 .,:()/_-]` becomes a space (this drops quotes, `$`, backticks,
 * backslashes and `!`, so the title is safe in the double quotes of the command
 * and in an AppleScript literal), then it is cut at a word boundary. Same rule
 * as section 3 step 8 of the ticket skill.
 */
export function shortSummary(summary) {
  const clean = String(summary ?? "")
    .replace(/[^A-Za-z0-9 .,:()/_-]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
  if (clean.length <= MAX_SHORT) return clean
  const window = clean.slice(0, MAX_SHORT)
  if (clean[MAX_SHORT] === " ") return window
  const space = window.lastIndexOf(" ")
  return (space > 0 ? window.slice(0, space) : window).trim()
}

/**
 * Title of a session: tab title, `claude --name` and the Remote Control name.
 * `<KEY> · <summary>` for a new ticket, `<KEY> resume · <summary>` for a run
 * that is resumed; without a summary just the key (and purpose).
 */
export function sessionName({ key, args = [], summary }) {
  const head = args.includes("--resume") ? `${key} resume` : key
  const short = shortSummary(summary)
  return short ? `${head} · ${short}` : head
}

/** Same rule as section 3 step 3 of the ticket skill. */
export function slugify(title) {
  const slug = String(title ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
    .replace(/-+$/g, "")
  return slug || "work"
}

/**
 * The terminal app the launcher runs in, which is where its sessions open:
 * `orca`, `iterm`, or null for anything else. Same rule as section 0 of the
 * ticket skill: TERM_PROGRAM decides first, because a terminal started from
 * another one can inherit its variables; ORCA_TERMINAL_HANDLE and
 * ITERM_SESSION_ID cover a multiplexer such as tmux.
 */
export function detectHost(env = process.env) {
  if (env.TERM_PROGRAM === "iTerm.app") return "iterm"
  if (env.TERM_PROGRAM === "Orca") return "orca"
  if (env.ORCA_TERMINAL_HANDLE) return "orca"
  if (env.ITERM_SESSION_ID) return "iterm"
  return null
}

/** The GUID in ITERM_SESSION_ID ("w0t1p0:<GUID>"), or null if there is none. */
export function iTermSessionId(env = process.env) {
  return /^[^:]*:([0-9A-Za-z-]+)$/.exec(env.ITERM_SESSION_ID ?? "")?.[1] ?? null
}

export function buildShellCommand({
  cwd,
  key,
  args = [],
  remoteControl = false,
  summary = null,
}) {
  if (!isSafeKey(key))
    throw new Error(`Invalid ticket key: ${JSON.stringify(key)}`)
  if (typeof cwd !== "string" || !path.isAbsolute(cwd) || /[\n\r\0]/.test(cwd))
    throw new Error(`cwd must be an absolute path: ${JSON.stringify(cwd)}`)
  for (const arg of args) {
    if (!ALLOWED_ARGS.has(arg))
      throw new Error(`Argument not allowed: ${JSON.stringify(arg)}`)
  }
  if (typeof remoteControl !== "boolean")
    throw new Error(
      `remoteControl must be a boolean: ${JSON.stringify(remoteControl)}`,
    )
  const prompt = ["/ticket", key, ...args].join(" ")
  // The title only holds a checked key, a fixed purpose word and a summary
  // reduced to a safe character set, so double quotes are safe. The flags go
  // before the prompt so the prompt stays positional.
  const title = sessionName({ key, args, summary })
  const rc = remoteControl ? `--remote-control "${title}" ` : ""
  return `cd ${shellQuote(cwd)} && TICKET_FLOW_KEY=${key} claude --name "${title}" ${rc}"${prompt}"`
}

export function buildAppleScript({
  command,
  key,
  args = [],
  sessionId = null,
  summary = null,
}) {
  const name = sessionName({ key, args, summary })
  // Without a match, for example after the launcher's tab was closed, the tab
  // goes to the frontmost window.
  const findWindow = sessionId
    ? [
        "\trepeat with w in windows",
        "\t\trepeat with t in tabs of w",
        "\t\t\trepeat with s in sessions of t",
        `\t\t\t\tif id of s is ${appleScriptString(sessionId)} then`,
        "\t\t\t\t\tset targetId to id of w",
        "\t\t\t\t\tset targetWindow to first window whose id is targetId",
        "\t\t\t\tend if",
        "\t\t\tend repeat",
        "\t\tend repeat",
        "\tend repeat",
      ]
    : []
  return [
    'tell application "iTerm2"',
    "\tactivate",
    "\tset targetWindow to missing value",
    ...findWindow,
    "\tif targetWindow is missing value and (count of windows) > 0 then",
    "\t\tset targetWindow to current window",
    "\tend if",
    "\tif targetWindow is missing value then",
    "\t\tcreate window with default profile",
    "\t\ttell current session of current window",
    `\t\t\tset name to ${appleScriptString(name)}`,
    `\t\t\twrite text ${appleScriptString(command)}`,
    "\t\tend tell",
    "\telse",
    "\t\ttell targetWindow",
    "\t\t\tcreate tab with default profile",
    "\t\t\ttell current session",
    `\t\t\t\tset name to ${appleScriptString(name)}`,
    `\t\t\t\twrite text ${appleScriptString(command)}`,
    "\t\t\tend tell",
    "\t\tend tell",
    "\tend if",
    "end tell",
  ].join("\n")
}

/**
 * `selector` names the Orca worktree the tab opens in. Without it,
 * `workspaceId` (ORCA_WORKTREE_ID) keeps the tab next to the launcher. The
 * session still runs in `cwd`, because the command starts with a cd.
 */
export function buildOrcaArgs({
  cwd,
  command,
  key,
  args = [],
  workspaceId = null,
  selector = null,
  summary = null,
}) {
  return [
    "terminal",
    "create",
    "--worktree",
    selector ?? (workspaceId ? `id:${workspaceId}` : `path:${cwd}`),
    "--title",
    sessionName({ key, args, summary }),
    "--command",
    command,
    "--json",
  ]
}

// ---------------------------------------------------------------------------
// Process and file helpers
// ---------------------------------------------------------------------------

function defaultRun(file, argv) {
  return new Promise((resolve, reject) => {
    execFile(file, argv, (error, stdout, stderr) => {
      // The orca CLI reports errors as JSON on stdout.
      if (error)
        reject(
          new Error(
            `${file} failed: ${(stderr || stdout || error.message).trim()}`,
          ),
        )
      else resolve({ stdout, stderr })
    })
  })
}

/** The terminal handle in the JSON `orca terminal create` prints, or null. */
function terminalHandle(stdout) {
  try {
    const out = JSON.parse(stdout)
    return (
      out?.result?.terminal?.handle ??
      out?.result?.handle ??
      out?.handle ??
      null
    )
  } catch {
    return null
  }
}

/** The main checkout of the repository `cwd` belongs to. */
export async function findRoot({ cwd, run = defaultRun }) {
  const { stdout } = await run("git", [
    "-C",
    cwd,
    "worktree",
    "list",
    "--porcelain",
  ])
  const first = /^worktree (.+)$/m.exec(String(stdout))?.[1]
  if (!first) throw new Error(`${cwd} is not inside a git repository`)
  return first
}

/** `.claude/gated-dev.json` of `root`, with defaults. Throws on invalid content. */
export function readConfig({ root, fs = nodeFs }) {
  const file = path.join(root, ".claude", "gated-dev.json")
  let raw = {}
  if (fs.existsSync(file)) {
    try {
      raw = JSON.parse(fs.readFileSync(file, "utf8"))
    } catch (error) {
      throw new Error(`${file}: invalid JSON (${error.message})`)
    }
    if (raw === null || typeof raw !== "object" || Array.isArray(raw))
      throw new Error(`${file}: must contain a JSON object`)
    for (const k of Object.keys(raw)) {
      if (!CONFIG_KEYS.has(k)) throw new Error(`${file}: unknown key "${k}"`)
    }
  }
  const ticketsDir = raw.ticketsDir ?? "docs/tickets"
  if (
    typeof ticketsDir !== "string" ||
    !ticketsDir ||
    path.isAbsolute(ticketsDir) ||
    ticketsDir.split(/[\\/]/).includes("..")
  )
    throw new Error(`${file}: ticketsDir must be a relative path inside the repo`)
  let keyPattern
  try {
    keyPattern = new RegExp(raw.keyPattern ?? DEFAULT_KEY_PATTERN)
  } catch (error) {
    throw new Error(`${file}: invalid keyPattern (${error.message})`)
  }
  const baseBranch = raw.baseBranch ?? null
  if (baseBranch !== null && !SAFE_REF.test(String(baseBranch)))
    throw new Error(`${file}: invalid baseBranch`)
  return { ticketsDir, keyPattern, baseBranch }
}

/** Checks a key against the safe set and the configured pattern. */
export function checkKey(key, config) {
  if (!isSafeKey(key) || !config.keyPattern.test(key))
    throw new Error(
      `${JSON.stringify(key)} is not a valid ticket key (keyPattern ${config.keyPattern.source})`,
    )
}

/**
 * `{ file, title, base }` of `<root>/<ticketsDir>/<KEY>/ticket.md`. `base` is the
 * front matter `base:` or null. Throws when the file is missing or has no title.
 */
export function readTicket({ root, key, config, fs = nodeFs }) {
  const file = path.join(root, config.ticketsDir, key, "ticket.md")
  if (!fs.existsSync(file))
    throw new Error(`${key}: no ticket file at ${path.relative(root, file)}`)
  const text = fs.readFileSync(file, "utf8")
  let body = text
  let base = null
  const front = /^---\r?\n([\s\S]*?)\r?\n---\r?\n/.exec(text)
  if (front) {
    body = text.slice(front[0].length)
    const m = /^base:(.*)$/m.exec(front[1])
    if (m) {
      const value = m[1].trim().replace(/^(["'])(.*)\1$/, "$2")
      if (!SAFE_REF.test(value)) throw new Error(`${key}: invalid base "${value}"`)
      base = value
    }
  }
  const title = /^# +(.+?)\s*$/m.exec(body)?.[1]
  if (!title) throw new Error(`${key}: ticket.md has no "# " title`)
  return { file, title, base }
}

/** Keys of every `<ticketsDir>/<KEY>/ticket.md` in the main checkout. */
export function listTicketKeys({ root, config, fs = nodeFs }) {
  const dir = path.join(root, config.ticketsDir)
  if (!fs.existsSync(dir)) return []
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name)
    .filter(
      (k) =>
        isSafeKey(k) &&
        config.keyPattern.test(k) &&
        fs.existsSync(path.join(dir, k, "ticket.md")),
    )
    .sort()
}

/**
 * The ticket's run: the worktree on a `<KEY>/*` branch, with the `stage` of its
 * `state.json` (null without one). Aborted runs are ignored. Returns null when
 * there is no run; throws when several are left.
 */
export async function findRun({ root, key, config, run = defaultRun, fs = nodeFs }) {
  const { stdout } = await run("git", [
    "-C",
    root,
    "worktree",
    "list",
    "--porcelain",
  ])
  const runs = []
  for (const block of String(stdout).split(/\n\n+/)) {
    const wt = /^worktree (.+)$/m.exec(block)?.[1]
    const branch = /^branch refs\/heads\/(.+)$/m.exec(block)?.[1]
    if (!wt || !branch?.startsWith(`${key}/`)) continue
    let stage = null
    try {
      const state = path.join(wt, config.ticketsDir, key, "state.json")
      stage = JSON.parse(fs.readFileSync(state, "utf8")).stage ?? null
    } catch {}
    if (stage !== "aborted") runs.push({ path: wt, branch, stage })
  }
  if (runs.length > 1)
    throw new Error(
      `${key}: several runs (${runs.map((r) => r.branch).join(", ")}); open the one you want with /ticket ${key} --resume`,
    )
  return runs[0] ?? null
}

/**
 * The branch a new ticket starts from: front matter `base:`, config
 * `baseBranch`, the remote default branch, `main` (section 3 step 2 of the skill).
 */
export async function resolveBase({ root, ticket, config, run = defaultRun }) {
  if (ticket.base) return ticket.base
  if (config.baseBranch) return config.baseBranch
  try {
    const { stdout } = await run("git", [
      "-C",
      root,
      "symbolic-ref",
      "--short",
      "refs/remotes/origin/HEAD",
    ])
    const ref = String(stdout).trim().replace(/^origin\//, "")
    if (SAFE_REF.test(ref)) return ref
  } catch {}
  return "main"
}

/** True when Orca knows the repository at `root`. */
export async function orcaHasRepo({ root, run = defaultRun }) {
  try {
    await run("orca", ["repo", "show", "--repo", `path:${root}`, "--json"])
    return true
  } catch {
    return false
  }
}

/** The arguments of `orca worktree create` for a new ticket. */
export function orcaWorktreeArgs({ root, key, title, base }) {
  const slug = slugify(title)
  return [
    "worktree",
    "create",
    "--repo",
    `path:${root}`,
    "--name",
    `${key.toLowerCase()}-${slug}`,
    "--branch",
    `${key}/${slug}`,
    "--base-branch",
    `origin/${base}`,
    "--setup",
    "skip",
    "--json",
  ]
}

/**
 * Creates the ticket's worktree through Orca, copies the developer's local
 * Claude settings and the ticket file into it. Returns `{ id, path, branch,
 * selector }`.
 */
export async function createOrcaWorktree({
  root,
  key,
  ticket,
  config,
  base,
  run = defaultRun,
  fs = nodeFs,
  log = () => {},
}) {
  const argv = orcaWorktreeArgs({ root, key, title: ticket.title, base })
  const { stdout } = await run("orca", argv)
  let out
  try {
    out = JSON.parse(stdout)
  } catch {
    throw new Error("orca worktree create printed no JSON")
  }
  const wt = out.result?.worktree ?? out.result ?? out
  const id = wt?.id ?? null
  const wtPath = wt?.path ?? wt?.git?.path
  if (typeof wtPath !== "string" || !path.isAbsolute(wtPath))
    throw new Error("orca worktree create returned no worktree path")
  const copy = (source, target, what) => {
    try {
      fs.mkdirSync(path.dirname(target), { recursive: true })
      fs.copyFileSync(source, target)
    } catch {
      // Path only: the settings file may hold permissions or secrets.
      log(`${key}: could not copy ${what} to ${target}`)
    }
  }
  const settings = path.join(root, ".claude", "settings.local.json")
  if (fs.existsSync(settings))
    copy(
      settings,
      path.join(wtPath, ".claude", "settings.local.json"),
      "settings.local.json",
    )
  // The session reads the ticket from its own checkout; the base branch may
  // not carry it.
  const ticketTarget = path.join(wtPath, config.ticketsDir, key, "ticket.md")
  if (!fs.existsSync(ticketTarget)) copy(ticket.file, ticketTarget, "ticket.md")
  return {
    id,
    path: wtPath,
    branch: argv[argv.indexOf("--branch") + 1],
    selector: id ? `id:${id}` : `path:${wtPath}`,
  }
}

// ---------------------------------------------------------------------------
// Launching
// ---------------------------------------------------------------------------

/**
 * Opens one tab running the session command. `host` is `orca` or `iterm`;
 * `selector` is the Orca worktree to open the tab in (Orca only). Returns
 * `{ command, title }`.
 */
export async function launchTab({
  host,
  cwd,
  key,
  args = [],
  remoteControl = false,
  summary = null,
  selector = null,
  env = process.env,
  run = defaultRun,
  log = () => {},
}) {
  const title = sessionName({ key, args, summary })
  const command = buildShellCommand({ cwd, key, args, remoteControl, summary })
  if (host === "orca") {
    const created = await run(
      "orca",
      buildOrcaArgs({
        cwd,
        command,
        key,
        args,
        workspaceId: env.ORCA_WORKTREE_ID ?? null,
        selector,
        summary,
      }),
    )
    // Orca retitles a tab that runs Claude, so set the title once more.
    const handle = terminalHandle(created?.stdout)
    if (handle) {
      try {
        await run("orca", [
          "terminal",
          "rename",
          "--terminal",
          handle,
          "--title",
          title,
        ])
      } catch (error) {
        log(`${key}: could not rename the tab (${error.message})`)
      }
    }
  } else if (host === "iterm") {
    const script = buildAppleScript({
      command,
      key,
      args,
      sessionId: iTermSessionId(env),
      summary,
    })
    await run("osascript", script.split("\n").flatMap((l) => ["-e", l]))
  } else {
    throw new Error(`unknown host ${JSON.stringify(host)}`)
  }
  return { command, title }
}

/**
 * Plans and (unless `dryRun`) opens the session for one ticket. Returns
 * `{ key, mode, host, cwd, command, title, base, worktree, note, launched }`
 * where `mode` is `resume`, `orca-worktree` or `main-checkout`.
 * A dry run calls only read-only commands (`git worktree list`,
 * `git symbolic-ref`, `orca repo show`).
 */
export async function launchTicket({
  root,
  key,
  config,
  remoteControl = false,
  dryRun = false,
  env = process.env,
  run = defaultRun,
  fs = nodeFs,
  log = () => {},
}) {
  checkKey(key, config)
  const host = detectHost(env)
  if (!host && !dryRun)
    throw new Error(
      `open sessions from Orca or iTerm2 (TERM_PROGRAM=${env.TERM_PROGRAM ?? "unset"}); --dry-run works anywhere`,
    )
  const base = { key, host, base: null, worktree: null, note: null }
  const open = async (plan) => {
    const result = { ...base, ...plan, launched: false }
    result.title = sessionName({ key, args: plan.args, summary: plan.summary })
    result.command = buildShellCommand({
      cwd: plan.cwd,
      key,
      args: plan.args,
      remoteControl,
      summary: plan.summary,
    })
    if (dryRun) return result
    await launchTab({
      host,
      cwd: plan.cwd,
      key,
      args: plan.args,
      remoteControl,
      summary: plan.summary,
      selector: plan.selector ?? null,
      env,
      run,
      log,
    })
    return { ...result, launched: true }
  }

  const existing = await findRun({ root, key, config, run, fs })
  if (existing) {
    let summary = null
    try {
      summary = readTicket({ root: existing.path, key, config, fs }).title
    } catch {}
    return open({
      mode: "resume",
      cwd: existing.path,
      args: ["--resume"],
      summary,
      note: existing.stage === "done" ? "run is done; resuming restarts the PR watch" : null,
      worktree: existing,
      selector: `path:${existing.path}`,
    })
  }

  const ticket = readTicket({ root, key, config, fs })
  const summary = ticket.title
  const mainCheckout = (note) =>
    open({ mode: "main-checkout", cwd: root, args: [], summary, note })
  if (host !== "orca") return mainCheckout(null)
  if (!(await orcaHasRepo({ root, run })))
    return mainCheckout(`${root} is not an Orca repo; the skill creates a git worktree`)

  const branchBase = await resolveBase({ root, ticket, config, run })
  if (dryRun) {
    const argv = orcaWorktreeArgs({ root, key, title: ticket.title, base: branchBase })
    return {
      ...base,
      mode: "orca-worktree",
      base: branchBase,
      cwd: `<new Orca worktree ${argv[argv.indexOf("--name") + 1]}>`,
      title: sessionName({ key, summary }),
      command: `orca ${argv.map((a) => (/^[\w:./@-]+$/.test(a) ? a : shellQuote(a))).join(" ")}`,
      note: `then /ticket ${key} in the new worktree`,
      launched: false,
    }
  }
  await run("git", ["-C", root, "fetch", "origin", branchBase])
  // A failure from here on must not fall back to the main checkout: the
  // session would create a second worktree.
  const worktree = await createOrcaWorktree({
    root,
    key,
    ticket,
    config,
    base: branchBase,
    run,
    fs,
    log,
  })
  return {
    ...(await open({
      mode: "orca-worktree",
      cwd: worktree.path,
      args: [],
      summary,
      worktree,
      selector: worktree.selector,
    })),
    base: branchBase,
  }
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

const USAGE = `Usage: launch.mjs [--dry-run] [--remote-control] (KEY... | --all)

Opens one Claude Code session per ticket, running /ticket <KEY>, in a new
Orca or iTerm2 tab. A ticket with a run is resumed in its worktree.

  KEY...            tickets to open (<ticketsDir>/<KEY>/ticket.md)
  --all             every ticket file in the main checkout that has no run yet
  --dry-run         print what would be opened; run nothing
  --remote-control  also start each session with --remote-control
  --cwd DIR         a directory inside the repository (default: current)`

export function parseArgs(argv) {
  const opts = { keys: [], all: false, dryRun: false, remoteControl: false, cwd: null, help: false }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === "--all") opts.all = true
    else if (a === "--dry-run" || a === "-n") opts.dryRun = true
    else if (a === "--remote-control") opts.remoteControl = true
    else if (a === "--help" || a === "-h") opts.help = true
    else if (a === "--cwd") {
      opts.cwd = argv[++i]
      if (!opts.cwd) throw new Error("--cwd needs a directory")
    } else if (a.startsWith("-")) throw new Error(`unknown option ${a}`)
    else opts.keys.push(a)
  }
  if (!opts.help && opts.all === (opts.keys.length > 0))
    throw new Error("give ticket keys or --all (not both)")
  return opts
}

function describe(r) {
  const lines = [`${r.key}: ${r.mode}${r.launched ? " (opened)" : ""}`]
  if (r.host !== undefined) lines.push(`  host:    ${r.host ?? "none (dry run only)"}`)
  if (r.base) lines.push(`  base:    ${r.base}`)
  if (r.cwd) lines.push(`  cwd:     ${r.cwd}`)
  if (r.title) lines.push(`  title:   ${r.title}`)
  if (r.command) lines.push(`  command: ${r.command}`)
  if (r.note) lines.push(`  note:    ${r.note}`)
  return lines.join("\n")
}

/** Runs the CLI; returns the exit code. */
export async function main(argv, {
  env = process.env,
  run = defaultRun,
  fs = nodeFs,
  out = console.log,
  err = console.error,
} = {}) {
  let opts
  try {
    opts = parseArgs(argv)
  } catch (error) {
    err(`${error.message}\n\n${USAGE}`)
    return 2
  }
  if (opts.help) {
    out(USAGE)
    return 0
  }
  let root, config
  try {
    root = await findRoot({ cwd: opts.cwd ?? process.cwd(), run })
    config = readConfig({ root, fs })
  } catch (error) {
    err(error.message)
    return 1
  }
  let keys = opts.keys
  if (opts.all) {
    keys = []
    for (const key of listTicketKeys({ root, config, fs })) {
      try {
        if (!(await findRun({ root, key, config, run, fs }))) keys.push(key)
      } catch {}
    }
    if (!keys.length) {
      out(`no ticket without a run in ${config.ticketsDir}`)
      return 0
    }
  }
  let failed = 0
  for (const key of keys) {
    try {
      const r = await launchTicket({
        root,
        key,
        config,
        remoteControl: opts.remoteControl,
        dryRun: opts.dryRun,
        env,
        run,
        fs,
        log: err,
      })
      out(describe(r))
    } catch (error) {
      failed++
      err(`${key}: ${error.message}`)
    }
  }
  return failed ? 1 : 0
}

const invoked =
  process.argv[1] &&
  nodeFs.realpathSync(process.argv[1]) ===
    nodeFs.realpathSync(fileURLToPath(import.meta.url))
if (invoked) process.exitCode = await main(process.argv.slice(2))
