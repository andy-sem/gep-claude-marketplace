import { test } from "node:test"
import assert from "node:assert/strict"
import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { MARKER, POLL_MS, main, normalizePr, parsePrUrl, watch } from "../scripts/watch-pr.mjs"

const PR_URL = "https://github.com/o/r/pull/7"
const T0 = "2026-10-22T08:00:00Z"
const T1 = "2026-10-22T09:00:00Z"
const T2 = "2026-10-22T10:00:00Z"
const CLOCK = new Date("2026-10-22T12:00:00Z")

const view = (extra = {}) => ({
  state: "OPEN",
  mergedAt: null,
  createdAt: T0,
  reviews: [],
  comments: [],
  ...extra,
})
const comment = (createdAt, extra = {}) => ({
  author: { login: "alice" },
  body: "please change this",
  createdAt,
  ...extra,
})

function setup(stateExtra = {}) {
  const dir = mkdtempSync(join(tmpdir(), "watch-pr-"))
  const ticketDir = join(dir, "docs", "tickets", "PROJ-9")
  mkdirSync(ticketDir, { recursive: true })
  const statePath = join(ticketDir, "state.json")
  const initial = {
    key: "PROJ-9",
    stage: "done",
    prUrl: PR_URL,
    updatedAt: "2026-10-22T07:00:00Z",
    ...stateExtra,
  }
  writeFileSync(statePath, JSON.stringify(initial, null, 2))
  return { dir, ticketDir, statePath, initial }
}

/**
 * Scripted gh: each poll consumes the next entry of `polls` (the last one
 * repeats). An entry is a `gh pr view` object, an Error, or { inline: [...], ...view }.
 */
function fakeRun(polls) {
  const calls = []
  let index = -1
  let count = 0
  let current = null
  const run = async (cmd, args) => {
    calls.push({ cmd, args })
    if (cmd !== "gh") throw new Error(`unexpected command ${cmd}`)
    if (args[0] === "pr") {
      count += 1
      index = Math.min(index + 1, polls.length - 1)
      current = polls[index]
      if (current instanceof Error) throw current
      const { inline, ...rest } = current
      void inline
      return JSON.stringify(rest)
    }
    const inline = current?.inline ?? []
    return inline.map((c) => JSON.stringify(c)).join("\n")
  }
  return { run, calls, polls: () => count }
}

const readState = (statePath) => JSON.parse(readFileSync(statePath, "utf8"))

function harness(polls, stateExtra) {
  const h = setup(stateExtra)
  h.gh = fakeRun(polls)
  h.sleeps = []
  h.logs = []
  h.onSleep = null
  h.deps = {
    statePath: h.statePath,
    run: h.gh.run,
    now: () => CLOCK,
    sleep: async (ms) => {
      h.sleeps.push(ms)
      if (h.onSleep) await h.onSleep(h.sleeps.length)
    },
    log: (line) => h.logs.push(line),
    pid: 4242,
  }
  return h
}

test("a human issue comment newer than the PR creation exits with feedback", async () => {
  const h = harness([view({ comments: [comment(T1)] })])
  const res = await watch(h.deps)
  assert.equal(res.outcome, "feedback")
  assert.equal(res.prUrl, PR_URL)
  assert.equal(res.newestAt, T1)
})

test("a review and an inline comment count as feedback", async () => {
  const review = {
    author: { login: "bob" },
    body: "needs work",
    state: "CHANGES_REQUESTED",
    submittedAt: T1,
  }
  const a = await watch(harness([view({ reviews: [review] })]).deps)
  assert.equal(a.outcome, "feedback")
  const b = await watch(
    harness([
      view({ inline: [{ login: "carol", body: "nit", createdAt: T2 }] }),
    ]).deps,
  )
  assert.equal(b.outcome, "feedback")
  assert.equal(b.newestAt, T2)
})

test("the cutoff is lastAddressedCommentAt, else the PR creation time", async () => {
  const withCutoff = harness(
    [view({ comments: [comment(T1)] }), view({ state: "MERGED" })],
    {
      lastAddressedCommentAt: T1,
    },
  )
  const res = await watch(withCutoff.deps)
  assert.equal(res.outcome, "merged")
  assert.deepEqual(withCutoff.sleeps, [POLL_MS])

  const older = harness([
    view({ comments: [comment(T0)] }),
    view({ state: "CLOSED" }),
  ])
  assert.equal((await watch(older.deps)).outcome, "closed")
})

test("a cutoff written to the file between polls is honoured", async () => {
  const h = harness([
    view({ comments: [comment(T1)] }),
    view({ comments: [comment(T1)] }),
  ])
  // The first poll is covered by the cutoff; the file changes during the
  // sleep, and the next poll must read the new cutoff.
  writeFileSync(
    h.statePath,
    JSON.stringify({ ...readState(h.statePath), lastAddressedCommentAt: T2 }),
  )
  h.onSleep = async (n) => {
    if (n === 1) {
      writeFileSync(
        h.statePath,
        JSON.stringify({
          ...readState(h.statePath),
          lastAddressedCommentAt: T0,
        }),
      )
    }
  }
  const res = await watch(h.deps)
  assert.equal(res.outcome, "feedback")
  assert.equal(h.sleeps.length, 1)
})

test("bots, pipeline replies, empty comments and empty reviews never exit", async () => {
  const noise = view({
    comments: [
      comment(T1, { author: { login: "github-actions[bot]" } }),
      comment(T1, { body: `done ${MARKER}` }),
      comment(T1, { body: "   " }),
    ],
    reviews: [
      {
        author: { login: "bob" },
        body: "",
        state: "COMMENTED",
        submittedAt: T1,
      },
      {
        author: { login: "bob" },
        body: "",
        state: "APPROVED",
        submittedAt: T1,
      },
    ],
    inline: [{ login: "x[bot]", body: "lint", createdAt: T1 }],
  })
  const h = harness([noise, noise, view({ state: "MERGED" })])
  const res = await watch(h.deps)
  assert.equal(res.outcome, "merged")
  assert.equal(h.sleeps.length, 2)
})

test("MERGED and CLOSED exit with their outcome", async () => {
  assert.equal(
    (await watch(harness([view({ state: "MERGED" })]).deps)).outcome,
    "merged",
  )
  assert.equal(
    (await watch(harness([view({ state: "CLOSED" })]).deps)).outcome,
    "closed",
  )
})

test("MERGED wins over feedback", async () => {
  const res = await watch(
    harness([view({ state: "MERGED", comments: [comment(T1)] })]).deps,
  )
  assert.equal(res.outcome, "merged")
})

test("five consecutive gh failures exit with error", async () => {
  const fail = new Error("gh: network down")
  const h = harness([fail])
  const res = await watch(h.deps)
  assert.equal(res.outcome, "error")
  assert.match(res.message, /network down/)
  assert.equal(h.gh.polls(), 5)
  assert.equal(h.sleeps.length, 4)
})

test("four failures, a success, four failures do not exit", async () => {
  const fail = new Error("boom")
  const ok = view()
  const h = harness([
    fail,
    fail,
    fail,
    fail,
    ok,
    fail,
    fail,
    fail,
    fail,
    view({ state: "MERGED" }),
  ])
  const res = await watch(h.deps)
  assert.equal(res.outcome, "merged")
  assert.equal(h.gh.polls(), 10)
})

test("a missing or invalid state.json counts as a failed poll", async () => {
  const h = harness([view({ state: "MERGED" })])
  writeFileSync(h.statePath, "{ not json")
  const res = await watch(h.deps)
  assert.equal(res.outcome, "error")
  assert.equal(h.gh.polls(), 0)

  const h2 = harness([view({ state: "MERGED" })])
  writeFileSync(h2.statePath, JSON.stringify({ stage: "done" }))
  assert.equal((await watch(h2.deps)).outcome, "error")
})

test("every poll writes the heartbeat and keeps every other field", async () => {
  const h = harness([view(), view({ state: "MERGED" })], {
    prNumber: 7,
    lastAddressedCommentAt: T0,
    extra: { a: 1 },
  })
  let seen
  h.onSleep = async () => {
    seen = readState(h.statePath)
  }
  await watch(h.deps)
  assert.equal(seen.watch.heartbeatAt, CLOCK.toISOString())
  assert.equal(seen.watch.pid, 4242)
  assert.equal(seen.watch.startedAt, CLOCK.toISOString())
  const final = readState(h.statePath)
  assert.equal(final.watch.heartbeatAt, CLOCK.toISOString())
  for (const [k, v] of Object.entries(h.initial)) assert.deepEqual(final[k], v)
  assert.equal(final.updatedAt, h.initial.updatedAt)
  assert.deepEqual(
    readdirSync(h.ticketDir).filter((f) => f.endsWith(".tmp")),
    [],
  )
})

test("the heartbeat is written after a failed poll too", async () => {
  const h = harness([new Error("x"), view({ state: "MERGED" })])
  let seen
  h.onSleep = async () => {
    seen = readState(h.statePath)
  }
  await watch(h.deps)
  assert.equal(seen.watch.heartbeatAt, CLOCK.toISOString())
})

test("startedAt stays the first poll time while heartbeatAt advances", async () => {
  const h = harness([view(), view({ state: "MERGED" })])
  let tick = 0
  h.deps.now = () => new Date(CLOCK.getTime() + tick++ * 60_000)
  await watch(h.deps)
  const w = readState(h.statePath).watch
  assert.equal(w.startedAt, CLOCK.toISOString())
  assert.notEqual(w.heartbeatAt, w.startedAt)
})

test("every sleep is 60000 ms and only gh is run", async () => {
  const h = harness([view(), view(), view({ state: "MERGED" })])
  await watch(h.deps)
  assert.deepEqual(h.sleeps, [60000, 60000])
  assert.ok(h.gh.calls.length > 0)
  assert.ok(h.gh.calls.every((c) => c.cmd === "gh"))
})

test("a failed heartbeat write is logged and does not stop the watcher", async () => {
  const h = harness([view({ state: "MERGED" })])
  // A directory where the tmp file would go makes the write fail.
  mkdirSync(`${h.statePath}.4242.tmp`)
  const res = await watch(h.deps)
  assert.equal(res.outcome, "merged")
  assert.ok(h.logs.some((l) => /heartbeat/.test(l)))
})

function mainHarness(polls, stateExtra) {
  const h = harness(polls, stateExtra)
  h.out = []
  h.deps = { ...h.deps, out: (line) => h.out.push(line) }
  return h
}

test("main prints one JSON line and returns the exit code per outcome", async () => {
  const cases = [
    [[view({ comments: [comment(T1)] })], "feedback", 0],
    [[view({ state: "MERGED" })], "merged", 0],
    [[view({ state: "CLOSED" })], "closed", 0],
    [[new Error("down")], "error", 1],
  ]
  for (const [polls, outcome, code] of cases) {
    const h = mainHarness(polls)
    const exit = await main(["--state", h.statePath], h.deps)
    assert.equal(exit, code, outcome)
    assert.equal(h.out.length, 1)
    assert.ok(!h.out[0].includes("\n".repeat(2)))
    const parsed = JSON.parse(h.out[0])
    assert.equal(parsed.outcome, outcome)
    assert.equal(parsed.prUrl, PR_URL)
    assert.equal(parsed.at, CLOCK.toISOString())
    if (outcome === "feedback") assert.equal(parsed.newestAt, T1)
    if (outcome === "error") assert.ok(parsed.message)
  }
})

test("main returns 2 with a usage line for a missing or relative --state", async () => {
  for (const argv of [
    [],
    ["--state"],
    ["--state", "docs/tickets/PROJ-9/state.json"],
    ["--bogus"],
  ]) {
    const out = []
    const exit = await main(argv, {
      out: (l) => out.push(l),
      log: () => {},
    })
    assert.equal(exit, 2)
    assert.equal(out.length, 1)
    const parsed = JSON.parse(out[0])
    assert.equal(parsed.outcome, "usage")
    assert.ok(parsed.message)
  }
})

test("parsePrUrl and normalizePr", () => {
  assert.deepEqual(parsePrUrl(PR_URL), { owner: "o", repo: "r", number: 7 })
  assert.equal(parsePrUrl("not a url"), null)
  const pr = normalizePr(
    view({ reviews: [{ author: { login: "b" }, body: "x", state: "COMMENTED", createdAt: T1 }] }),
    [{ login: "c", body: "y", createdAt: T2 }],
  )
  assert.deepEqual(pr.feedback.map((f) => f.login), ["b", "c"])
  assert.equal(pr.feedback[0].createdAt, T1)
})

test("a PR url that cannot be parsed counts as a failed poll", async () => {
  const h = harness([view({ state: "MERGED" })], { prUrl: "nope" })
  const res = await watch(h.deps)
  assert.equal(res.outcome, "error")
  assert.match(res.message, /cannot parse/)
})
