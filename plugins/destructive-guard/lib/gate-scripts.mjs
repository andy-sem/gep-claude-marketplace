// Script collection and scan for the approval gate. When a Bash command runs a
// project file (a shell script, a Node or Python file, a package script, a GitHub
// workflow) this module finds the file, follows `source` and relative imports a few
// levels deep, and reports the contents so the gate can
//   - scan them for gated programs and cloud references (the fallback rules), and
//   - hand them to Jev as context.
// It names no concrete tool: programs come from the CLI rules, patterns and exempt
// globs from the rules file. gate-engine.mjs loads this module with a dynamic
// import() so the two modules never form a static import cycle.

import {
  closeSync,
  existsSync,
  openSync,
  readdirSync,
  readFileSync,
  readSync,
  realpathSync,
  statSync,
} from "node:fs"
import {
  basename,
  dirname,
  extname,
  isAbsolute,
  join,
  resolve,
} from "node:path"
import {
  nestedShellString,
  shellScriptIndex,
  splitCommand,
  stripWrappers,
} from "./gate-engine.mjs"

export const MAX_FILE_BYTES = 65536
export const MAX_FOLLOW_DEPTH = 3
export const MAX_FILES = 32

const SHELLS = new Set(["bash", "sh", "zsh"])
const JS_EXT = /\.(?:[cm]?[jt]s|[jt]sx)$/
const SHELL_EXT = /\.(?:sh|bash|zsh)$/
const PYTHON_RE = /^python(?:\d+(?:\.\d+)?)?$/
const NODE_PRELOAD_OPTS = ["-r", "--require", "--import", "--loader"]
const NODE_VALUE_OPTS = [
  ...NODE_PRELOAD_OPTS,
  "-C",
  "--conditions",
  "--env-file",
  "--input-type",
]
const PKG_DIR_OPTS = ["-C", "--dir", "--prefix", "--cwd"]
const NPM_LIFECYCLE = new Set(["test", "start", "stop", "restart"])

// ---------------------------------------------------------------------------
// Project root and paths
// ---------------------------------------------------------------------------

function realOrSelf(p) {
  try {
    return realpathSync(p)
  } catch {
    return p
  }
}

// The nearest ancestor of `cwd` that has a `.git` entry (a directory, or the file a
// worktree has), else CLAUDE_PROJECT_DIR, else `cwd`. Always realpath'd.
export function findProjectRoot(cwd, env = process.env) {
  let dir = resolve(cwd)
  for (;;) {
    if (existsSync(join(dir, ".git"))) return realOrSelf(dir)
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return realOrSelf(env.CLAUDE_PROJECT_DIR || cwd)
}

function inside(root, real) {
  return (
    real === root || real.startsWith(root.endsWith("/") ? root : `${root}/`)
  )
}

function relPath(root, abs) {
  const real = realOrSelf(abs)
  if (inside(root, real)) return real.slice(root.length + 1) || "."
  if (inside(root, abs)) return abs.slice(root.length + 1) || "."
  return abs
}

// A small glob matcher for `**/`, `**`, `*` and `?`; every other character is literal.
export function globToRegExp(glob) {
  let out = ""
  for (let i = 0; i < glob.length; i++) {
    const c = glob[i]
    if (c === "*" && glob[i + 1] === "*") {
      if (glob[i + 2] === "/") {
        out += "(?:.*/)?"
        i += 2
      } else {
        out += ".*"
        i += 1
      }
    } else if (c === "*") out += "[^/]*"
    else if (c === "?") out += "[^/]"
    else out += c.replace(/[.+^${}()|[\]\\]/g, "\\$&")
  }
  return new RegExp(`^${out}$`)
}

function isExemptPath(rel, rules) {
  return (rules.scriptScanExempt ?? []).some((g) => globToRegExp(g).test(rel))
}

// ---------------------------------------------------------------------------
// Which project files does a command run?
// ---------------------------------------------------------------------------

// A word that cannot be resolved to a path now: expansions, substitutions and globs.
function unresolvable(token) {
  return /[$*?[\u0000]/.test(token) || token === "{}" || token.startsWith("~")
}

// Strips leading options. `valueOpts` take a value (separate, attached to a short
// option or `--opt=value`).
function leadingOptions(tokens, valueOpts) {
  const values = {}
  let k = 0
  while (k < tokens.length) {
    const t = tokens[k]
    if (!t.startsWith("-") || t === "-") break
    k++
    if (t === "--") break
    const eq = t.indexOf("=")
    if (t.startsWith("--")) {
      if (eq !== -1) values[t.slice(0, eq)] = t.slice(eq + 1)
      else if (valueOpts.includes(t)) values[t] = tokens[k++]
    } else if (valueOpts.includes(t)) {
      values[t] = tokens[k++]
    } else if (t.length > 2 && valueOpts.includes(t.slice(0, 2))) {
      values[t.slice(0, 2)] = t.slice(2)
    }
  }
  return { rest: tokens.slice(k), values }
}

function nodeOperands(args) {
  const files = []
  let script
  let testMode = false
  let i = 0
  for (; i < args.length; i++) {
    const t = args[i]
    if (t === "--") {
      i++
      break
    }
    if (!t.startsWith("-") || t === "-") break
    if (t === "--test") {
      testMode = true
      continue
    }
    if (t === "--run" || t.startsWith("--run=")) {
      script = t === "--run" ? args[++i] : t.slice(6)
      continue
    }
    if (t === "--eval" || t === "--print" || /^-[a-zA-Z]*[ep]$/.test(t))
      return { files, script, eval: true }
    if (t.startsWith("--eval=") || t.startsWith("--print="))
      return { files, script, eval: true }
    const eq = t.indexOf("=")
    const name = eq === -1 ? t : t.slice(0, eq)
    if (NODE_PRELOAD_OPTS.includes(name)) {
      files.push(eq === -1 ? args[++i] : t.slice(eq + 1))
    } else if (eq === -1 && NODE_VALUE_OPTS.includes(name)) {
      i++
    } else if (/^-[rC]./.test(t) && !t.startsWith("--")) {
      if (t[1] === "r") files.push(t.slice(2))
    }
  }
  if (i < args.length) {
    if (testMode) files.push(...args.slice(i))
    else files.push(args[i])
  }
  return { files, script }
}

function pythonOperand(args) {
  for (let i = 0; i < args.length; i++) {
    const t = args[i]
    if (t === "-m" || t === "-c" || /^-[mc]./.test(t)) return null
    if (t === "-W" || t === "-X") {
      i++
      continue
    }
    if (t === "-" || !t.startsWith("-")) return t === "-" ? null : t
  }
  return null
}

function firstOperand(args, valueOpts = []) {
  return leadingOptions(args, valueOpts).rest[0]
}

function readScripts(pkgFile) {
  try {
    const scripts = JSON.parse(readFileSync(pkgFile, "utf8"))?.scripts
    return scripts && typeof scripts === "object" ? scripts : null
  } catch {
    return null
  }
}

// Top-level `name:` of a workflow file.
function workflowName(file) {
  try {
    const m = /^name:\s*["']?(.+?)["']?\s*$/m.exec(readFileSync(file, "utf8"))
    return m ? m[1] : null
  } catch {
    return null
  }
}

function resolveWorkflow(arg, root) {
  const dir = join(root, ".github", "workflows")
  if (/\.ya?ml$/.test(arg)) return { path: join(dir, basename(arg)) }
  if (/^\d+$/.test(arg)) return null
  let names
  try {
    names = readdirSync(dir).filter((f) => /\.ya?ml$/.test(f))
  } catch {
    return null
  }
  for (const f of names.sort()) {
    if (workflowName(join(dir, f)) === arg) return { path: join(dir, f) }
  }
  return null
}

// `terraform test` (or `tofu test`, also as a container entrypoint such as `docker run
// -w <dir> --entrypoint terraform <image> test`) runs the `*.tftest.hcl` files of the
// root module and of its test directory. They decide whether the run touches the cloud
// (`mock_provider`, `command = plan|apply`), so they go to Jev as `{ path, cwd,
// context: true }` targets. Context files are exempt from the script scan: the
// terraform rule already judges the command. Returns [] when the directory is dynamic.
const TF_PROGRAMS = new Set(["terraform", "tofu"])
const WORKDIR_OPTS = ["-w", "--workdir"]
const CONTAINERS = new Set(["docker", "podman"])

function optionValue(tokens, names) {
  for (let i = 0; i < tokens.length; i++) {
    for (const n of names) {
      if (tokens[i] === n) return tokens[i + 1] ?? ""
      if (tokens[i].startsWith(`${n}=`)) return tokens[i].slice(n.length + 1)
    }
  }
  return undefined
}

function terraformTestTargets(tokens, cwd) {
  const idx = tokens.findIndex((t) => TF_PROGRAMS.has(basename(t)))
  if (idx < 0) return []
  const rest = tokens.slice(idx + 1)
  if (!rest.filter((t) => !t.startsWith("-")).includes("test")) return []
  let dir = cwd
  if (idx > 0) {
    // only a local container sees the same files; `ssh host terraform test` does not
    if (!CONTAINERS.has(basename(tokens[0])) || tokens[1] !== "run") return []
    // without -w the container starts in the image's directory, not ours
    const workdir = optionValue(tokens.slice(0, idx), WORKDIR_OPTS)
    if (!workdir || unresolvable(workdir) || !isAbsolute(workdir)) return []
    dir = workdir
  }
  const chdir = optionValue(rest, ["-chdir"])
  if (chdir !== undefined) {
    if (unresolvable(chdir) || !dir) return []
    dir = resolve(dir, chdir)
  }
  const testDir = optionValue(rest, ["-test-directory"]) ?? "tests"
  if (!dir || unresolvable(testDir)) return []
  const out = []
  for (const d of [dir, resolve(dir, testDir)]) {
    let names
    try {
      names = readdirSync(d).sort()
    } catch {
      continue
    }
    for (const name of names) {
      if (name.endsWith(".tftest.hcl"))
        out.push({ path: join(d, name), cwd: dir, context: true })
    }
  }
  return out
}

// The project files one simple command runs: `{ path, cwd }` for a file, `{ path,
// script }` for a package script (`path` is its package.json). Paths are absolute,
// resolved against `cwd`; `cwd` is null once a `cd` target was dynamic. A file's `cwd`
// is the directory the command ran in, which a `source ./x` inside it is relative to.
export function runTargets(rawTokens, rules, { cwd, root }, depth = 0) {
  if (depth > 4) return []
  let stripped
  try {
    stripped = stripWrappers(rawTokens, rules).tokens
  } catch {
    return []
  }
  if (!stripped.length) return []
  const word = stripped[0]
  const base = basename(word)
  const args = stripped.slice(1)
  const out = []
  // A shell command string handed over by a wrapper or runner (`watch bash x.sh`,
  // `npx -c '…'`); a plain `bash -c '…'` is already split out by splitCommand.
  const first = rawTokens.find((t) => !/^[A-Za-z_]\w*=/.test(t))
  if (first !== undefined && !SHELLS.has(basename(first))) {
    const nested = nestedShellString(rawTokens, rules)
    if (nested !== null) {
      out.push(...commandTargets(nested, rules, cwd, root, depth + 1))
    }
  }
  const file = (arg, from = cwd) => {
    if (typeof arg !== "string" || arg === "" || unresolvable(arg)) return
    if (isAbsolute(arg)) out.push({ path: arg, cwd })
    else if (from) out.push({ path: resolve(from, arg), cwd: from })
  }

  out.push(...terraformTestTargets(stripped, cwd))

  if (word === "source" || word === ".") {
    file(args[0])
    return out
  }
  if (SHELLS.has(base) && (!word.includes("/") || isAbsolute(word))) {
    const idx = shellScriptIndex(stripped)
    if (idx > 0) file(stripped[idx])
    return out
  }
  if (base === "node" && (!word.includes("/") || isAbsolute(word))) {
    const info = nodeOperands(args)
    info.files.forEach((f) => file(f))
    if (info.script && cwd)
      out.push({ path: join(cwd, "package.json"), script: info.script })
    return out
  }
  if (PYTHON_RE.test(base) && (!word.includes("/") || isAbsolute(word))) {
    file(pythonOperand(args))
    return out
  }
  if (base === "tsx" && !word.includes("/")) {
    const rest = leadingOptions(args, ["--tsconfig", "-r", "--import"]).rest
    file(rest[0] === "watch" ? rest[1] : rest[0])
    return out
  }
  if (base === "deno" && !word.includes("/")) {
    const rest = leadingOptions(args, []).rest
    if (rest[0] === "run") file(leadingOptions(rest.slice(1), []).rest[0])
    return out
  }
  if (base === "gh" && args[0] === "workflow" && args[1] === "run") {
    const operand = firstOperand(args.slice(2), [
      "-r",
      "--ref",
      "-f",
      "--raw-field",
      "-F",
      "--field",
      "-R",
      "--repo",
    ])
    if (operand && !unresolvable(operand)) {
      const wf = resolveWorkflow(operand, root)
      if (wf) out.push(wf)
    }
    return out
  }

  const runner = rules.runners.find((r) => r.program === base)
  if (runner && ["pnpm", "npm", "yarn", "bun"].includes(base)) {
    const { rest, values } = leadingOptions(args, runner.valueOptions)
    const dirOpt = PKG_DIR_OPTS.map((o) => values[o]).find((v) => v)
    if (dirOpt !== undefined && unresolvable(dirOpt)) return out
    const pkgDir = dirOpt ? resolve(cwd ?? root, dirOpt) : cwd
    const pkgFile = pkgDir ? join(pkgDir, "package.json") : null
    const script = (name) => {
      if (pkgFile && name && !unresolvable(name))
        out.push({ path: pkgFile, script: name })
    }
    if (rest[0] === "run" || rest[0] === "run-script") {
      const after = leadingOptions(rest.slice(1), runner.valueOptions)
      script(after.rest[0])
      return out
    }
    if (base === "npm" && NPM_LIFECYCLE.has(rest[0])) {
      script(rest[0])
      return out
    }
    if (base !== "npm" && rest[0] && pkgFile) {
      const scripts = readScripts(pkgFile)
      if (scripts && Object.hasOwn(scripts, rest[0])) {
        script(rest[0])
        return out
      }
    }
    // A runner that runs another program: `pnpm exec node x.mjs`, `npx tsx x.ts`.
    let next = rest
    if (next.length && runner.subcommands.includes(next[0])) {
      next = leadingOptions(next.slice(1), runner.valueOptions).rest
    } else if (!runner.bareBin) {
      return out
    }
    if (next.length) {
      out.push(
        ...runTargets(next, rules, { cwd: pkgDir ?? cwd, root }, depth + 1),
      )
    }
    return out
  }
  if (runner && runner.bareBin) {
    const next = leadingOptions(args, runner.valueOptions).rest
    if (next.length) {
      out.push(...runTargets(next, rules, { cwd, root }, depth + 1))
    }
    return out
  }
  // `./x.sh`, `infra/cloud/apply.sh`; an absolute path outside the project is a system
  // program, not a script
  if (word.includes("/") && !word.startsWith("-")) {
    const systemProgram =
      isAbsolute(word) && !inside(root, realOrSelf(word)) && !inside(root, word)
    if (!systemProgram) file(word)
  }
  return out
}

// Targets of a whole command string. A literal `cd <dir>` or `pushd <dir>` moves the
// directory for the commands after it in the same scope, `popd` goes back; after a
// dynamic or missing target relative files are dropped. A `cd` inside a `( … )` group
// or a substitution does not move the directory of the commands after the group.
// Commands of a string a shell was given with `-c` start in the directory the shell
// command itself ran in (`scope.host`), not the one the main command ended in.
//
// Variables assigned earlier in the same command (`P=$D/infra; cd $P`) are expanded;
// anything else stays a `$` word, which is unresolvable.
const ASSIGNMENT_RE = /^[A-Za-z_]\w*=/

function expandVars(token, vars) {
  if (!vars.size || !token.includes("$")) return token
  return token.replace(
    /\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))/g,
    (m, braced, bare) => vars.get(braced ?? bare) ?? m,
  )
}

function commandTargets(command, rules, cwd, root, depth = 0) {
  let simple
  try {
    simple = splitCommand(command)
  } catch {
    return []
  }
  const out = []
  // per scope: the directory and the pushd stack
  const states = new Map()
  // per command: the state it ran in, for the strings it hosts
  const snapshots = new Map()
  let mainRoot
  const stateOf = (scope) => {
    let state = states.get(scope)
    if (state) return state
    const copy = (s) => ({
      here: s.here,
      stack: [...s.stack],
      vars: new Map(s.vars),
    })
    if (scope.parent) {
      state = copy(stateOf(scope.parent))
    } else if (scope.host && snapshots.has(scope.host)) {
      state = copy(snapshots.get(scope.host))
    } else if (mainRoot === undefined) {
      mainRoot = scope
      state = { here: cwd, stack: [], vars: new Map() }
    } else {
      state = copy(states.get(mainRoot))
    }
    states.set(scope, state)
    return state
  }
  for (const raw of simple) {
    const state = raw.scope
      ? stateOf(raw.scope)
      : { here: cwd, stack: [], vars: new Map() }
    snapshots.set(raw, {
      here: state.here,
      stack: [...state.stack],
      vars: new Map(state.vars),
    })
    const tokens = raw.map((t) => expandVars(t, state.vars))
    for (const key of Object.keys(raw)) {
      if (!/^\d+$/.test(key)) tokens[key] = raw[key]
    }
    // `D=/abs; P=$D/x`: a command of assignments only sets variables for the commands
    // after it; `X=1 cmd` sets X for cmd alone
    if (tokens.length && tokens.every((t) => ASSIGNMENT_RE.test(t))) {
      for (const t of tokens) {
        const eq = t.indexOf("=")
        state.vars.set(t.slice(0, eq), t.slice(eq + 1))
      }
      continue
    }
    let stripped = tokens
    try {
      stripped = stripWrappers(tokens, rules).tokens
    } catch {}
    const word = stripped[0]
    if (word === "cd" || word === "pushd") {
      const target = stripped.slice(1).find((t) => !t.startsWith("-"))
      if (word === "pushd") state.stack.push(state.here)
      state.here =
        state.here && target && !unresolvable(target) && target !== "-"
          ? resolve(state.here, target)
          : null
      continue
    }
    if (word === "popd") {
      state.here = state.stack.length ? state.stack.pop() : null
      continue
    }
    out.push(...runTargets(tokens, rules, { cwd: state.here, root }, depth))
  }
  return out
}

// ---------------------------------------------------------------------------
// Following source and imports
// ---------------------------------------------------------------------------

const SCRIPT_DIR_RE = [
  /"?\$\(\s*dirname\s+"?\$\{?(?:0|BASH_SOURCE(?:\[0\])?)\}?"?\s*\)"?/g,
  /\$\{(?:BASH_SOURCE(?:\[0\])?|0)%\/\*\}/g,
  /\$\{?(?:SCRIPT_DIR|SCRIPTDIR|HERE|DIR)\}?/g,
]
const ROOT_DIR_RE = /\$\{?(?:REPO_ROOT|ROOT_DIR|PROJECT_ROOT)\}?/g

function sourceTargets(content, scriptDir, cwd, root) {
  const out = []
  const re =
    /(?:^|[;&|({]|\bthen\b|\bdo\b|\belse\b)[ \t]*(?:source|\.)[ \t]+([^\n]+)/gm
  for (let m; (m = re.exec(content)); ) {
    let arg = m[1]
    for (const sd of SCRIPT_DIR_RE) arg = arg.replace(sd, "\u0001")
    arg = arg.replace(ROOT_DIR_RE, "\u0002")
    arg = arg.replace(/["']/g, "")
    arg = arg.split(/[\s;&|)]/)[0]
    if (!arg || unresolvable(arg.replace(/[\u0001\u0002]/g, ""))) continue
    if (arg.startsWith("\u0001")) arg = join(scriptDir, arg.slice(1))
    else if (arg.startsWith("\u0002")) arg = join(root, arg.slice(1))
    else if (!isAbsolute(arg)) {
      if (!cwd) continue
      arg = resolve(cwd, arg)
    }
    if (!arg.includes("\u0001") && !arg.includes("\u0002"))
      out.push({ path: arg })
  }
  return out
}

const IMPORT_RES = [
  /\b(?:import|export)\b[^'"`;]*?\bfrom\s*(['"])([^'"\n]+)\1/g,
  /\bimport\s*(['"])([^'"\n]+)\1/g,
  /\b(?:import|require)\s*\(\s*(['"])([^'"\n]+)\1\s*\)/g,
]
const TRY_EXT = [".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx", ".jsx"]

function isFile(p) {
  try {
    return statSync(p).isFile()
  } catch {
    return false
  }
}

function resolveImport(dir, spec) {
  const base = resolve(dir, spec)
  const candidates = [base]
  const swap = { ".js": ".ts", ".mjs": ".mts", ".cjs": ".cts", ".jsx": ".tsx" }
  const ext = extname(base)
  if (swap[ext]) candidates.push(base.slice(0, -ext.length) + swap[ext])
  for (const e of TRY_EXT) candidates.push(base + e)
  for (const e of TRY_EXT) candidates.push(join(base, `index${e}`))
  return candidates.find(isFile) ?? base
}

function importTargets(content, dir) {
  const found = []
  for (const re of IMPORT_RES) {
    re.lastIndex = 0
    for (let m; (m = re.exec(content)); ) {
      const spec = m[2]
      if (spec.startsWith("./") || spec.startsWith("../")) {
        found.push({ at: m.index, spec })
      }
    }
  }
  // source order, whichever pattern matched
  return found
    .sort((a, b) => a.at - b.at)
    .map((f) => ({ path: resolveImport(dir, f.spec) }))
}

function kindOf(path, content) {
  if (JS_EXT.test(path)) return "js"
  if (SHELL_EXT.test(path)) return "shell"
  const shebang = /^#!\s*(\S+)(?:\s+(\S+))?/.exec(content)
  if (shebang) {
    const prog = basename(
      basename(shebang[1]) === "env" ? (shebang[2] ?? "") : shebang[1],
    )
    if (SHELLS.has(prog)) return "shell"
    if (/^(?:node|tsx|deno|bun)$/.test(prog)) return "js"
    return "other"
  }
  return extname(path) === "" ? "shell" : "other"
}

function readHead(real, size) {
  const fd = openSync(real, "r")
  try {
    const buf = Buffer.alloc(Math.min(size, MAX_FILE_BYTES))
    const n = readSync(fd, buf, 0, buf.length, 0)
    return buf.subarray(0, n).toString("utf8")
  } finally {
    closeSync(fd)
  }
}

// Reads the files `command` runs and the files they pull in (breadth-first, in
// source order). Returns `{ files, problems }`:
// - files: `{ path, content, size, truncated, exempt, depth }`, `path` relative to
//   the project root (a package script is `<dir>/package.json#scripts.<name>`);
// - problems: `{ path, reason, exempt }` for files the gate could not read safely.
// A missing file is skipped. An unparsable command gives nothing: the rule layer
// already asks for it.
export function collectScripts(command, rules, { cwd, root }) {
  const files = []
  const problems = []
  const seen = new Set()
  // the directory a target's own command ran in, else the one of the file it came from
  const cwdOf = (t, from) => (Object.hasOwn(t, "cwd") ? t.cwd : from)
  const queue = commandTargets(command, rules, cwd, root).map((t) => ({
    ...t,
    depth: 0,
    parentExempt: false,
    cwd: cwdOf(t, cwd),
  }))
  let capped = false
  for (let qi = 0; qi < queue.length; qi++) {
    const item = queue[qi]
    let real
    try {
      real = realpathSync(item.path)
    } catch (e) {
      if (e?.code === "ENOENT" || e?.code === "ENOTDIR") continue
      problems.push({
        path: relPath(root, item.path),
        reason: "is unreadable",
        exempt: item.parentExempt,
      })
      continue
    }
    const key = item.script ? `${real}#${item.script}` : real
    if (seen.has(key)) continue
    seen.add(key)
    const shown = item.script
      ? `${relPath(root, item.path)}#scripts.${item.script}`
      : relPath(root, item.path)
    const exempt =
      item.parentExempt ||
      item.context === true ||
      isExemptPath(shown.split("#")[0], rules)
    const problem = (reason) => problems.push({ path: shown, reason, exempt })
    if (!inside(root, real)) {
      problem("is outside the project")
      continue
    }
    let st
    try {
      st = statSync(real)
    } catch {
      problem("is unreadable")
      continue
    }
    if (!st.isFile()) {
      problem("is not a regular file")
      continue
    }
    if (files.length >= MAX_FILES) {
      if (!capped)
        problems.push({
          path: shown,
          reason: `more than ${MAX_FILES} files`,
          exempt: false,
        })
      capped = true
      break
    }
    let content
    let size = st.size
    let truncated = false
    try {
      content = readHead(real, st.size)
    } catch {
      problem("is unreadable")
      continue
    }
    if (item.script) {
      let body
      try {
        body = JSON.parse(readFileSync(real, "utf8"))?.scripts?.[item.script]
      } catch {
        problem("is unreadable")
        continue
      }
      if (typeof body !== "string") continue
      content = body
      size = Buffer.byteLength(body)
    }
    if (size > MAX_FILE_BYTES) {
      truncated = true
      content = content.slice(0, MAX_FILE_BYTES)
      problem("exceeds 64 KB")
    }
    files.push({
      path: shown,
      content,
      size,
      truncated,
      exempt,
      depth: item.depth,
    })

    if (item.depth >= MAX_FOLLOW_DEPTH) continue
    const dir = dirname(real)
    let next = []
    if (item.script) {
      next = commandTargets(content, rules, dir, root)
    } else {
      const kind = kindOf(real, content)
      if (kind === "shell") next = sourceTargets(content, dir, item.cwd, root)
      else if (kind === "js") next = importTargets(content, dir)
    }
    for (const t of next) {
      queue.push({
        ...t,
        depth: item.depth + 1,
        parentExempt: exempt,
        cwd: cwdOf(t, item.cwd),
      })
    }
  }
  return { files, problems }
}

// ---------------------------------------------------------------------------
// Scan
// ---------------------------------------------------------------------------

function ask(id, detail) {
  return { decision: "ask", reason: `${id}: ${detail}` }
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

// The program names a script could run: those named by the CLI rules and by an
// mcp-as-cli rule (the rules file is the only place that names tools).
function programNames(rules) {
  const names = new Set()
  for (const rule of rules.rules) {
    if (rule.kind === "cli-allowlist" || rule.kind === "cli-gated") {
      if (rule.scriptScan === false) continue
      for (const p of rule.programs) names.add(p)
    } else if (rule.kind === "mcp-as-cli") {
      names.add(rule.program)
    }
  }
  return [...names]
}

// Looks at the non-exempt files and problems: an unreadable, outside-project or
// oversized file asks, then a program name, then a `scriptPatterns` match. Returns an
// `ask` result or null.
export function scanScripts(collected, rules) {
  if (!collected) return null
  // Nothing to look for: no program names and no patterns.
  if (!programNames(rules).length && !(rules.scriptPatterns ?? []).length)
    return null
  const problem = collected.problems.find((p) => !p.exempt)
  if (problem) return ask("script", `${problem.path} ${problem.reason}`)
  const files = collected.files.filter((f) => !f.exempt)
  const names = programNames(rules).map((name) => ({
    name,
    re: new RegExp(`(?<![\\w.@-])${escapeRe(name)}(?![\\w-])`),
  }))
  for (const f of files) {
    for (const { name, re } of names) {
      if (re.test(f.content)) return ask("script", `${f.path} runs ${name}`)
    }
  }
  for (const f of files) {
    for (const re of rules.scriptPatterns ?? []) {
      if (re.test(f.content))
        return ask("script", `${f.path} references ${re.source}`)
    }
  }
  return null
}
