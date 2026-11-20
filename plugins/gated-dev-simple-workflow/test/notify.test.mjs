import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { chmodSync, existsSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { test } from "node:test"
import { fileURLToPath } from "node:url"

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const script = path.join(root, "hooks", "notify.sh")

function findJq() {
  const r = spawnSync("bash", ["-c", "command -v jq"], { encoding: "utf8" })
  return r.status === 0 ? r.stdout.trim() : null
}
const jq = findJq()

// Stub bin dir: `uname` prints the given OS; osascript and notify-send record
// their arguments. PATH is only the stub dir plus /bin for bash builtins'
// helpers, so the real notifiers are never reached.
function run({ os = "Darwin", env = {}, input = "", withJq = true, notifiers = ["osascript", "notify-send"], args = [] } = {}) {
  const dir = mkdtempSync(path.join(tmpdir(), "notify-"))
  const log = path.join(dir, "log")
  const stub = (name, body) => {
    const p = path.join(dir, name)
    writeFileSync(p, `#!/bin/bash\n${body}\n`)
    chmodSync(p, 0o755)
  }
  stub("uname", `echo ${os}`)
  stub("cat", `exec /bin/cat "$@"`)
  for (const n of notifiers) stub(n, `printf '%s\\n' "${n}" "$@" > "${log}"`)
  if (withJq && jq) symlinkSync(jq, path.join(dir, "jq"))
  const r = spawnSync("/bin/bash", [script, ...args], {
    input,
    encoding: "utf8",
    env: { PATH: dir, ...env },
  })
  const calls = existsSync(log) ? readFileSync(log, "utf8").trimEnd().split("\n") : null
  return { status: r.status, stderr: r.stderr, calls }
}

const event = JSON.stringify({ hook_event_name: "Notification", message: "Claude needs your permission to use Bash" })

test("hooks.json registers notify.sh for Notification", () => {
  const cfg = JSON.parse(readFileSync(path.join(root, "hooks", "hooks.json"), "utf8"))
  const cmd = cfg.hooks.Notification[0].hooks[0].command
  assert.equal(cmd, 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/notify.sh"')
})

test("silent without TICKET_FLOW_KEY", () => {
  const r = run({ input: event })
  assert.equal(r.status, 0)
  assert.equal(r.calls, null)
})

test("GATED_DEV_NOTIFY=0 turns it off", () => {
  const r = run({ input: event, env: { TICKET_FLOW_KEY: "PROJ-1", GATED_DEV_NOTIFY: "0" } })
  assert.equal(r.status, 0)
  assert.equal(r.calls, null)
})

test("macOS: osascript with key title and the event message", { skip: !jq && "jq not installed" }, () => {
  const r = run({ input: event, env: { TICKET_FLOW_KEY: "PROJ-1" } })
  assert.equal(r.status, 0)
  assert.equal(r.calls[0], "osascript")
  assert.deepEqual(r.calls.slice(-2), ["PROJ-1 needs you", "Claude needs your permission to use Bash"])
  assert.ok(r.calls.includes("--"))
})

test("Linux: notify-send with key title and the event message", { skip: !jq && "jq not installed" }, () => {
  const r = run({ os: "Linux", input: event, env: { TICKET_FLOW_KEY: "PROJ-1" } })
  assert.equal(r.status, 0)
  assert.deepEqual(r.calls, ["notify-send", "--", "PROJ-1 needs you", "Claude needs your permission to use Bash"])
})

test("Linux without notify-send: silent, exit 0", () => {
  const r = run({ os: "Linux", input: event, env: { TICKET_FLOW_KEY: "PROJ-1" }, notifiers: [] })
  assert.equal(r.status, 0)
  assert.equal(r.calls, null)
})

test("other OS: silent, exit 0", () => {
  const r = run({ os: "FreeBSD", input: event, env: { TICKET_FLOW_KEY: "PROJ-1" } })
  assert.equal(r.status, 0)
  assert.equal(r.calls, null)
})

test("default message without jq or with bad input", () => {
  for (const opts of [{ withJq: false, input: event }, { input: "not json" }, { input: "" }]) {
    const r = run({ os: "Linux", env: { TICKET_FLOW_KEY: "PROJ-1" }, ...opts })
    assert.equal(r.status, 0)
    assert.deepEqual(r.calls.slice(-1), ["Claude needs your attention"])
  }
})

test("a failing notifier does not fail the hook", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "notify-"))
  writeFileSync(path.join(dir, "uname"), "#!/bin/bash\necho Darwin\n")
  writeFileSync(path.join(dir, "osascript"), "#!/bin/bash\necho boom >&2\nexit 1\n")
  writeFileSync(path.join(dir, "cat"), '#!/bin/bash\nexec /bin/cat "$@"\n')
  for (const f of ["uname", "osascript", "cat"]) chmodSync(path.join(dir, f), 0o755)
  const r = spawnSync("/bin/bash", [script], {
    input: event,
    encoding: "utf8",
    env: { PATH: dir, TICKET_FLOW_KEY: "PROJ-1" },
  })
  assert.equal(r.status, 0)
  assert.equal(r.stderr, "")
})

test("direct mode: title and message from arguments, no TICKET_FLOW_KEY needed", () => {
  const r = run({ os: "Linux", args: ["PROJ-1 merged", "PR #7 merged"] })
  assert.equal(r.status, 0)
  assert.deepEqual(r.calls, ["notify-send", "--", "PROJ-1 merged", "PR #7 merged"])
  const off = run({ os: "Linux", args: ["PROJ-1 merged", "x"], env: { GATED_DEV_NOTIFY: "0" } })
  assert.equal(off.calls, null)
})
