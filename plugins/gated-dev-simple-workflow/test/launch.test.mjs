import assert from "node:assert/strict"
import { test } from "node:test"
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import {
  appleScriptString,
  buildAppleScript,
  buildOrcaArgs,
  buildShellCommand,
  checkKey,
  createOrcaWorktree,
  detectHost,
  findRun,
  iTermSessionId,
  launchTab,
  launchTicket,
  listTicketKeys,
  main,
  orcaWorktreeArgs,
  parseArgs,
  readConfig,
  readTicket,
  resolveBase,
  sessionName,
  shortSummary,
  slugify,
} from "../scripts/launch.mjs"

// --- fixtures ---------------------------------------------------------------

function repo({ config, tickets = {} } = {}) {
  const root = mkdtempSync(path.join(tmpdir(), "launch-"))
  if (config !== undefined) {
    mkdirSync(path.join(root, ".claude"), { recursive: true })
    writeFileSync(
      path.join(root, ".claude", "gated-dev.json"),
      typeof config === "string" ? config : JSON.stringify(config),
    )
  }
  for (const [key, text] of Object.entries(tickets)) {
    mkdirSync(path.join(root, "docs/tickets", key), { recursive: true })
    writeFileSync(path.join(root, "docs/tickets", key, "ticket.md"), text)
  }
  return root
}

const porcelain = (entries) =>
  entries
    .map(([wt, branch]) => `worktree ${wt}\nHEAD abc\nbranch refs/heads/${branch}\n`)
    .join("\n")

// A fake `run`: answers by "<file> <first args>" prefix and records every call.
function fakeRun(answers = {}) {
  const calls = []
  const run = async (file, argv) => {
    calls.push([file, ...argv])
    const line = [file, ...argv].join(" ")
    const hit = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((k) => line.startsWith(k))
    if (hit === undefined) return { stdout: "" }
    const a = answers[hit]
    if (a instanceof Error) throw a
    return { stdout: typeof a === "function" ? a(argv) : a }
  }
  run.calls = calls
  return run
}

const ORCA = { TERM_PROGRAM: "Orca" }
const ITERM = { TERM_PROGRAM: "iTerm.app", ITERM_SESSION_ID: "w0t1p0:ABC-123" }
const cfg = (root) => readConfig({ root })

// --- names and commands -----------------------------------------------------

test("buildShellCommand quotes cwd, sets TICKET_FLOW_KEY and names the session", () => {
  assert.equal(
    buildShellCommand({ cwd: "/a b/c", key: "PROJ-1", args: ["--resume"] }),
    `cd '/a b/c' && TICKET_FLOW_KEY=PROJ-1 claude --name "PROJ-1 resume" "/ticket PROJ-1 --resume"`,
  )
  assert.equal(
    buildShellCommand({ cwd: "/x", key: "PROJ-1", summary: "Fix it", remoteControl: true }),
    `cd '/x' && TICKET_FLOW_KEY=PROJ-1 claude --name "PROJ-1 · Fix it" --remote-control "PROJ-1 · Fix it" "/ticket PROJ-1"`,
  )
})

test("buildShellCommand escapes single quotes in cwd", () => {
  assert.match(
    buildShellCommand({ cwd: `/it's/a"b\\c`, key: "K-1" }),
    /^cd '\/it'\\''s\/a"b\\c' &&/,
  )
})

test("buildShellCommand rejects unsafe keys, other args, relative cwd, bad remoteControl", () => {
  for (const key of ["", "a b", "K;rm", "K/1", "a..b", "$(x)", "-K"])
    assert.throws(() => buildShellCommand({ cwd: "/x", key }), /Invalid ticket key/)
  assert.throws(() => buildShellCommand({ cwd: "x", key: "K-1" }), /absolute/)
  assert.throws(() => buildShellCommand({ cwd: "/x\n", key: "K-1" }), /absolute/)
  assert.throws(
    () => buildShellCommand({ cwd: "/x", key: "K-1", args: ["--yolo"] }),
    /not allowed/,
  )
  assert.throws(
    () => buildShellCommand({ cwd: "/x", key: "K-1", remoteControl: "yes" }),
    /boolean/,
  )
})

test("shortSummary strips unsafe characters and cuts at a word boundary", () => {
  assert.equal(shortSummary(`Say "hi" $(rm -rf /) \`x\` \\ !`), "Say hi (rm -rf /) x")
  assert.equal(shortSummary(null), "")
  const long = "Export reports as CSV with filters and pagination support"
  assert.equal(shortSummary(long), "Export reports as CSV with filters and")
  assert.equal(shortSummary("a".repeat(50)), "a".repeat(40))
})

test("sessionName: key, resume and summary", () => {
  assert.equal(sessionName({ key: "K-1" }), "K-1")
  assert.equal(sessionName({ key: "K-1", args: ["--resume"] }), "K-1 resume")
  assert.equal(sessionName({ key: "K-1", summary: "Do it!" }), "K-1 · Do it")
})

test("a hostile title cannot reach the shell or AppleScript", () => {
  const summary = `"; do shell script "x" \`whoami\` $HOME '`
  const command = buildShellCommand({ cwd: "/x", key: "K-1", summary })
  assert.equal(command.match(/"/g).length, 4)
  assert.doesNotMatch(command.slice("cd '/x' ".length), /[`$']/)
  const script = buildAppleScript({ command, key: "K-1", summary })
  for (const line of script.split("\n").filter((l) => l.includes("set name to")))
    assert.match(line.trim(), /^set name to "[^"\\]*"$/)
})

test("slugify follows the skill rule", () => {
  assert.equal(slugify("Add slugify helper, and drop the legacy folder"), "add-slugify-helper-and-drop-the-legacy-f")
  assert.equal(slugify("  --Hello  World--  "), "hello-world")
  assert.equal(slugify("!!!"), "work")
  assert.equal(slugify("a".repeat(39) + " b"), "a".repeat(39))
})

test("detectHost: TERM_PROGRAM first, then Orca handle, then iTerm2 session id", () => {
  assert.equal(detectHost({ TERM_PROGRAM: "Orca" }), "orca")
  assert.equal(detectHost({ TERM_PROGRAM: "iTerm.app" }), "iterm")
  assert.equal(detectHost({ ORCA_TERMINAL_HANDLE: "t1" }), "orca")
  assert.equal(detectHost({ ITERM_SESSION_ID: "w0t0p0:X" }), "iterm")
  assert.equal(detectHost({ TERM_PROGRAM: "iTerm.app", ORCA_TERMINAL_HANDLE: "t1" }), "iterm")
  assert.equal(detectHost({ TERM_PROGRAM: "Orca", ITERM_SESSION_ID: "w0t0p0:X" }), "orca")
  assert.equal(detectHost({ TERM_PROGRAM: "Apple_Terminal" }), null)
  assert.equal(detectHost({}), null)
})

test("iTermSessionId takes the GUID and ignores unusable values", () => {
  assert.equal(iTermSessionId({ ITERM_SESSION_ID: "w0t1p0:AB-12" }), "AB-12")
  assert.equal(iTermSessionId({ ITERM_SESSION_ID: "garbage" }), null)
  assert.equal(iTermSessionId({ ITERM_SESSION_ID: 'w0:a"b' }), null)
  assert.equal(iTermSessionId({}), null)
})

test("buildAppleScript escapes, names the tab and targets the launcher's window", () => {
  assert.equal(appleScriptString(`a"b\\c`), `"a\\"b\\\\c"`)
  const script = buildAppleScript({ command: `cd '/x' && echo "hi"`, key: "K-1", sessionId: "S-1" })
  assert.match(script, /set name to "K-1"/)
  assert.match(script, /write text "cd '\/x' && echo \\"hi\\""/)
  assert.match(script, /if id of s is "S-1" then/)
  assert.doesNotMatch(buildAppleScript({ command: "c", key: "K-1" }), /repeat with w/)
})

test("buildOrcaArgs: selector, then the launcher's workspace, then the path", () => {
  const base = { cwd: "/r", command: "c", key: "K-1" }
  const at = (o) => buildOrcaArgs({ ...base, ...o })[3]
  assert.equal(at({ selector: "id:w1", workspaceId: "ws" }), "id:w1")
  assert.equal(at({ workspaceId: "ws" }), "id:ws")
  assert.equal(at({}), "path:/r")
  assert.deepEqual(buildOrcaArgs({ ...base, summary: "T" }).slice(4), [
    "--title", "K-1 · T", "--command", "c", "--json",
  ])
})

// --- config and tickets -----------------------------------------------------

test("readConfig: defaults, overrides and invalid content", () => {
  const d = cfg(repo())
  assert.equal(d.ticketsDir, "docs/tickets")
  assert.ok(d.keyPattern.test("proj-1"))
  assert.equal(d.baseBranch, null)
  const c = cfg(repo({ config: { ticketsDir: "t", keyPattern: "^[A-Z]+-\\d+$", baseBranch: "develop", models: {} } }))
  assert.equal(c.ticketsDir, "t")
  assert.equal(c.baseBranch, "develop")
  assert.ok(!c.keyPattern.test("proj-1"))
  for (const [bad, re] of [
    ["{", /invalid JSON/],
    ["[]", /JSON object/],
    [{ nope: 1 }, /unknown key "nope"/],
    [{ ticketsDir: "../x" }, /ticketsDir/],
    [{ ticketsDir: "/abs" }, /ticketsDir/],
    [{ keyPattern: "(" }, /keyPattern/],
    [{ baseBranch: "a b" }, /baseBranch/],
  ])
    assert.throws(() => cfg(repo({ config: bad })), re)
})

test("checkKey applies keyPattern and the safe character set", () => {
  const c = cfg(repo({ config: { keyPattern: "^[A-Z]+-\\d+$" } }))
  checkKey("PROJ-1", c)
  assert.throws(() => checkKey("proj-1", c), /not a valid ticket key/)
  const loose = cfg(repo({ config: { keyPattern: "." } }))
  assert.throws(() => checkKey("a;b", loose), /not a valid/)
  assert.throws(() => checkKey("a..b", loose), /not a valid/)
})

test("readTicket: title, front matter base, missing file and missing title", () => {
  const root = repo({
    tickets: {
      "K-1": "---\nbase: release/2.x\nowner: me\n---\n\n# Export CSV\n\nText",
      "K-2": "# Plain\n",
      "K-3": "no heading\n",
      "K-4": "---\nbase: 'a b'\n---\n# T\n",
      "K-5": "---\nbase: \"dev\"\n---\n# T\n",
    },
  })
  const c = cfg(root)
  const t = readTicket({ root, key: "K-1", config: c })
  assert.equal(t.title, "Export CSV")
  assert.equal(t.base, "release/2.x")
  assert.equal(readTicket({ root, key: "K-2", config: c }).base, null)
  assert.throws(() => readTicket({ root, key: "K-3", config: c }), /no "# " title/)
  assert.throws(() => readTicket({ root, key: "K-9", config: c }), /no ticket file/)
  assert.throws(() => readTicket({ root, key: "K-4", config: c }), /invalid base/)
  assert.equal(readTicket({ root, key: "K-5", config: c }).base, "dev")
})

test("listTicketKeys lists ticket dirs whose key matches", () => {
  const root = repo({
    config: { keyPattern: "^[A-Z]+-\\d+$" },
    tickets: { "K-2": "# a", "K-1": "# b", "notes": "# c" },
  })
  mkdirSync(path.join(root, "docs/tickets/K-3"))
  assert.deepEqual(listTicketKeys({ root, config: cfg(root) }), ["K-1", "K-2"])
  assert.deepEqual(listTicketKeys({ root: repo(), config: cfg(repo()) }), [])
})

test("findRun finds the <KEY>/* worktree, ignores aborted runs, rejects several", async () => {
  const root = repo()
  const c = cfg(root)
  const wt = (name, stage) => {
    const p = path.join(root, ".claude/worktrees", name)
    mkdirSync(path.join(p, "docs/tickets/K-1"), { recursive: true })
    if (stage) writeFileSync(path.join(p, "docs/tickets/K-1/state.json"), JSON.stringify({ stage }))
    return p
  }
  const a = wt("k-1-a", "dev")
  const b = wt("k-1-b", "aborted")
  const list = porcelain([[root, "main"], [a, "K-1/a"], [b, "K-1/b"], ["/o", "K-10/x"]])
  const run = fakeRun({ "git -C": list })
  assert.deepEqual(await findRun({ root, key: "K-1", config: c, run }), {
    path: a, branch: "K-1/a", stage: "dev",
  })
  assert.equal(await findRun({ root, key: "K-2", config: c, run }), null)
  const two = fakeRun({ "git -C": porcelain([[a, "K-1/a"], ["/nowhere", "K-1/c"]]) })
  await assert.rejects(findRun({ root, key: "K-1", config: c, run: two }), /several runs/)
})

test("resolveBase: front matter, config, origin/HEAD, main", async () => {
  const head = fakeRun({ "git -C /r symbolic-ref": "origin/trunk\n" })
  const none = fakeRun({ "git -C /r symbolic-ref": new Error("no") })
  const c = { baseBranch: null }
  assert.equal(await resolveBase({ root: "/r", ticket: { base: "rel" }, config: { baseBranch: "dev" }, run: head }), "rel")
  assert.equal(await resolveBase({ root: "/r", ticket: {}, config: { baseBranch: "dev" }, run: head }), "dev")
  assert.equal(await resolveBase({ root: "/r", ticket: {}, config: c, run: head }), "trunk")
  assert.equal(await resolveBase({ root: "/r", ticket: {}, config: c, run: none }), "main")
})

// --- Orca worktree ------------------------------------------------------------

test("orcaWorktreeArgs names the worktree and branch after key and title", () => {
  assert.deepEqual(orcaWorktreeArgs({ root: "/r", key: "K-1", title: "Do it", base: "main" }), [
    "worktree", "create", "--repo", "path:/r", "--name", "k-1-do-it",
    "--branch", "K-1/do-it", "--base-branch", "origin/main", "--setup", "skip", "--json",
  ])
})

test("createOrcaWorktree copies local settings and the ticket into the worktree", async () => {
  const root = repo({ tickets: { "K-1": "# Do it\n" } })
  writeFileSync(path.join(root, ".claude-placeholder"), "")
  mkdirSync(path.join(root, ".claude"), { recursive: true })
  writeFileSync(path.join(root, ".claude/settings.local.json"), '{"a":1}')
  const wtPath = mkdtempSync(path.join(tmpdir(), "wt-"))
  const run = fakeRun({ orca: JSON.stringify({ result: { worktree: { id: "w9", path: wtPath } } }) })
  const c = cfg(root)
  const ticket = readTicket({ root, key: "K-1", config: c })
  const wt = await createOrcaWorktree({ root, key: "K-1", ticket, config: c, base: "main", run })
  assert.deepEqual(wt, { id: "w9", path: wtPath, branch: "K-1/do-it", selector: "id:w9" })
  assert.equal(readFileSync(path.join(wtPath, ".claude/settings.local.json"), "utf8"), '{"a":1}')
  assert.equal(readFileSync(path.join(wtPath, "docs/tickets/K-1/ticket.md"), "utf8"), "# Do it\n")
})

test("createOrcaWorktree keeps a ticket the base branch carries, reads other JSON shapes", async () => {
  const root = repo({ tickets: { "K-1": "# New\n" } })
  const wtPath = mkdtempSync(path.join(tmpdir(), "wt-"))
  mkdirSync(path.join(wtPath, "docs/tickets/K-1"), { recursive: true })
  writeFileSync(path.join(wtPath, "docs/tickets/K-1/ticket.md"), "# Committed\n")
  const run = fakeRun({ orca: JSON.stringify({ path: wtPath }) })
  const c = cfg(root)
  const ticket = readTicket({ root, key: "K-1", config: c })
  const wt = await createOrcaWorktree({ root, key: "K-1", ticket, config: c, base: "main", run })
  assert.equal(wt.selector, `path:${wtPath}`)
  assert.equal(readFileSync(path.join(wtPath, "docs/tickets/K-1/ticket.md"), "utf8"), "# Committed\n")
  assert.ok(!existsSync(path.join(wtPath, ".claude/settings.local.json")))
})

test("createOrcaWorktree rejects output without JSON or without a path", async () => {
  const root = repo({ tickets: { "K-1": "# T\n" } })
  const c = cfg(root)
  const ticket = readTicket({ root, key: "K-1", config: c })
  for (const [stdout, re] of [["oops", /no JSON/], ['{"result":{}}', /no worktree path/], ['{"path":"rel"}', /no worktree path/]])
    await assert.rejects(
      createOrcaWorktree({ root, key: "K-1", ticket, config: c, base: "main", run: fakeRun({ orca: stdout }) }),
      re,
    )
})

// --- launchTab ----------------------------------------------------------------

test("launchTab in iTerm2 runs osascript with -e lines targeting the launcher's session", async () => {
  const run = fakeRun()
  await launchTab({ host: "iterm", cwd: "/r", key: "K-1", summary: "T", env: ITERM, run })
  assert.equal(run.calls.length, 1)
  const [file, ...argv] = run.calls[0]
  assert.equal(file, "osascript")
  assert.ok(argv.filter((_, i) => i % 2 === 0).every((a) => a === "-e"))
  assert.ok(argv.includes('\t\t\t\tif id of s is "ABC-123" then'))
})

test("launchTab in Orca creates the terminal, then renames it", async () => {
  const run = fakeRun({ "orca terminal create": '{"result":{"terminal":{"handle":"h1"}}}' })
  await launchTab({ host: "orca", cwd: "/w", key: "K-1", summary: "T", selector: "id:w9", env: ORCA, run })
  assert.deepEqual(run.calls.map((c) => c.slice(0, 3)), [["orca", "terminal", "create"], ["orca", "terminal", "rename"]])
  assert.equal(run.calls[0][4], "id:w9")
  assert.deepEqual(run.calls[1].slice(3), ["--terminal", "h1", "--title", "K-1 · T"])
})

test("launchTab in Orca: no handle means no rename; a failed rename is only logged", async () => {
  const quiet = fakeRun({ "orca terminal create": "not json" })
  await launchTab({ host: "orca", cwd: "/w", key: "K-1", env: ORCA, run: quiet })
  assert.equal(quiet.calls.length, 1)
  const logs = []
  const failing = fakeRun({
    "orca terminal create": '{"handle":"h1"}',
    "orca terminal rename": new Error("nope"),
  })
  await launchTab({ host: "orca", cwd: "/w", key: "K-1", env: ORCA, run: failing, log: (m) => logs.push(m) })
  assert.match(logs[0], /could not rename/)
})

// --- launchTicket -------------------------------------------------------------

function demo({ config, ticket = "# Do it\n", worktrees = [], registered = true, head = "origin/main" } = {}) {
  const root = repo({ config, tickets: ticket ? { "K-1": ticket } : {} })
  const wtPath = mkdtempSync(path.join(tmpdir(), "wt-"))
  const answers = {
    "git -C": porcelain([[root, "main"], ...worktrees]),
    [`git -C ${root} symbolic-ref`]: head,
    [`git -C ${root} fetch`]: "",
    "orca repo show": registered ? "{}" : new Error("unknown repo"),
    "orca worktree create": JSON.stringify({ result: { worktree: { id: "w9", path: wtPath } } }),
    "orca terminal create": '{"result":{"handle":"h1"}}',
  }
  return { root, wtPath, config: cfg(root), run: fakeRun(answers) }
}

test("launchTicket in Orca: fetch, Orca worktree, tab in that worktree", async () => {
  const { root, wtPath, config, run } = demo()
  const r = await launchTicket({ root, key: "K-1", config, env: ORCA, run })
  assert.equal(r.mode, "orca-worktree")
  assert.equal(r.base, "main")
  assert.equal(r.cwd, wtPath)
  assert.ok(r.launched)
  const seq = run.calls.map((c) => c.slice(0, 3).join(" "))
  assert.ok(seq.indexOf(`git -C ${root}`) >= 0)
  assert.ok(seq.includes("orca repo show"))
  const fetch = run.calls.find((c) => c.includes("fetch"))
  assert.deepEqual(fetch.slice(-2), ["origin", "main"])
  const create = run.calls.find((c) => c[1] === "terminal" && c[2] === "create")
  assert.equal(create[4], "id:w9")
  assert.match(create.at(-2), new RegExp(`^cd '${wtPath}' && TICKET_FLOW_KEY=K-1 claude --name "K-1 · Do it" "/ticket K-1"$`))
  assert.ok(existsSync(path.join(wtPath, "docs/tickets/K-1/ticket.md")))
})

test("launchTicket in Orca uses front matter base before config and origin/HEAD", async () => {
  const { root, config, run } = demo({ ticket: "---\nbase: rel\n---\n# T\n", config: { baseBranch: "dev" } })
  const r = await launchTicket({ root, key: "K-1", config, env: ORCA, run })
  assert.equal(r.base, "rel")
  assert.ok(run.calls.find((c) => c[0] === "orca" && c[1] === "worktree").includes("origin/rel"))
})

test("launchTicket in Orca with an unregistered repo opens in the main checkout", async () => {
  const { root, config, run } = demo({ registered: false })
  const r = await launchTicket({ root, key: "K-1", config, env: { ...ORCA, ORCA_WORKTREE_ID: "ws" }, run })
  assert.equal(r.mode, "main-checkout")
  assert.equal(r.cwd, root)
  assert.match(r.note, /not an Orca repo/)
  assert.ok(!run.calls.some((c) => c[1] === "worktree" || c.includes("fetch")))
  assert.equal(run.calls.find((c) => c[1] === "terminal")[4], "id:ws")
})

test("launchTicket in iTerm2 opens the main checkout and runs only osascript", async () => {
  const { root, config, run } = demo()
  const r = await launchTicket({ root, key: "K-1", config, env: ITERM, run, remoteControl: true })
  assert.equal(r.mode, "main-checkout")
  assert.match(r.command, /--remote-control "K-1 · Do it"/)
  assert.deepEqual(run.calls.map((c) => c[0]), ["git", "osascript"])
})

test("launchTicket resumes an existing run in its worktree", async () => {
  const wt = mkdtempSync(path.join(tmpdir(), "wt-"))
  mkdirSync(path.join(wt, "docs/tickets/K-1"), { recursive: true })
  writeFileSync(path.join(wt, "docs/tickets/K-1/ticket.md"), "# Do it\n")
  writeFileSync(path.join(wt, "docs/tickets/K-1/state.json"), '{"stage":"dev"}')
  const { root, config, run } = demo({ ticket: null, worktrees: [[wt, "K-1/do-it"]] })
  const r = await launchTicket({ root, key: "K-1", config, env: ORCA, run })
  assert.equal(r.mode, "resume")
  assert.equal(r.cwd, wt)
  assert.equal(r.title, "K-1 resume · Do it")
  const create = run.calls.find((c) => c[1] === "terminal")
  assert.equal(create[4], `path:${wt}`)
  assert.match(create.at(-2), /"\/ticket K-1 --resume"$/)
})

test("launchTicket skips a finished run", async () => {
  const wt = mkdtempSync(path.join(tmpdir(), "wt-"))
  mkdirSync(path.join(wt, "docs/tickets/K-1"), { recursive: true })
  writeFileSync(path.join(wt, "docs/tickets/K-1/state.json"), '{"stage":"done"}')
  const { root, config, run } = demo({ worktrees: [[wt, "K-1/x"]] })
  const r = await launchTicket({ root, key: "K-1", config, env: ITERM, run })
  assert.equal(r.mode, "skip")
  assert.ok(!r.launched)
  assert.ok(!run.calls.some((c) => c[0] === "osascript"))
})

test("launchTicket dry run changes nothing and plans the Orca worktree", async () => {
  const { root, config, run } = demo()
  const r = await launchTicket({ root, key: "K-1", config, env: ORCA, run, dryRun: true })
  assert.equal(r.mode, "orca-worktree")
  assert.match(r.command, /^orca worktree create --repo path:.* --branch K-1\/do-it --base-branch origin\/main/)
  const changing = run.calls.filter(
    (c) => c.includes("fetch") || (c[0] === "orca" && c[1] !== "repo") || c[0] === "osascript",
  )
  assert.deepEqual(changing, [])
})

test("launchTicket outside Orca/iTerm2 fails unless it is a dry run", async () => {
  const { root, config, run } = demo()
  await assert.rejects(
    launchTicket({ root, key: "K-1", config, env: {}, run }),
    /Orca or iTerm2/,
  )
  const r = await launchTicket({ root, key: "K-1", config, env: {}, run, dryRun: true })
  assert.equal(r.host, null)
  assert.equal(r.mode, "main-checkout")
})

test("launchTicket: a failing orca worktree create throws and never falls back", async () => {
  const { root, config, run } = demo()
  const failing = async (file, argv) => {
    if (file === "orca" && argv[0] === "worktree") throw new Error("boom")
    return run(file, argv)
  }
  failing.calls = run.calls
  await assert.rejects(launchTicket({ root, key: "K-1", config, env: ORCA, run: failing }), /boom/)
  assert.ok(!run.calls.some((c) => c[1] === "terminal"))
})

test("launchTicket rejects a key outside keyPattern and a ticket without a file", async () => {
  const { root, config, run } = demo({ config: { keyPattern: "^[A-Z]+-\\d+$" } })
  await assert.rejects(launchTicket({ root, key: "k-1", config, env: ITERM, run }), /not a valid/)
  await assert.rejects(launchTicket({ root, key: "K-2", config, env: ITERM, run }), /no ticket file/)
})

// --- CLI ------------------------------------------------------------------------

test("parseArgs: keys or --all, flags, errors", () => {
  assert.deepEqual(parseArgs(["-n", "--remote-control", "A-1", "B-2"]), {
    keys: ["A-1", "B-2"], all: false, dryRun: true, remoteControl: true, cwd: null, help: false,
  })
  assert.equal(parseArgs(["--all", "--cwd", "/r"]).cwd, "/r")
  assert.ok(parseArgs(["--help"]).help)
  assert.throws(() => parseArgs([]), /keys or --all/)
  assert.throws(() => parseArgs(["--all", "A-1"]), /keys or --all/)
  assert.throws(() => parseArgs(["--force", "A-1"]), /unknown option/)
  assert.throws(() => parseArgs(["--cwd"]), /needs a directory/)
})

test("main --all --dry-run plans every ticket without a run and reports failures per key", async () => {
  const root = repo({ tickets: { "A-1": "# One\n", "B-2": "# Two\n", "C-3": "no title" } })
  const wt = mkdtempSync(path.join(tmpdir(), "wt-"))
  const run = fakeRun({ "git -C": porcelain([[root, "main"], [wt, "B-2/two"]]) })
  const out = []
  const err = []
  const code = await main(["--all", "--dry-run", "--cwd", root], {
    env: ITERM, run, out: (m) => out.push(m), err: (m) => err.push(m),
  })
  assert.equal(code, 1)
  assert.match(out.join("\n"), /^A-1: main-checkout\n  host:    iterm/m)
  assert.doesNotMatch(out.join("\n"), /B-2/)
  assert.match(err.join("\n"), /C-3: .*no "# " title/)
})

test("main reports a config error and a usage error", async () => {
  const root = repo({ config: { bad: 1 } })
  const err = []
  const run = fakeRun({ "git -C": porcelain([[root, "main"]]) })
  assert.equal(await main(["K-1", "--cwd", root], { run, out: () => {}, err: (m) => err.push(m) }), 1)
  assert.match(err[0], /unknown key "bad"/)
  assert.equal(await main([], { run, out: () => {}, err: (m) => err.push(m) }), 2)
  assert.match(err[1], /Usage/)
})
