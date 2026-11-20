#!/usr/bin/env node
// PR watcher for a finished /ticket run: polls the run's pull request until
// there is something for the ticket session to do, then prints one JSON line
// and exits.
//
//   node watch-pr.mjs --state <abs>/<ticketsDir>/<KEY>/state.json
//
// Outcomes: feedback, merged, closed (exit 0: the JSON line says which, and
// Claude Code reports any non-zero exit of a background command as a
// failure), error (exit 1), usage (exit 2). stdout carries the final JSON line only; progress and errors go to
// stderr. Only `gh` is run. Every poll writes a heartbeat into state.json
// (`watch: {pid, startedAt, heartbeatAt}`), and nothing else in that file.

import { execFile } from "node:child_process"
import { readFileSync, realpathSync, renameSync, writeFileSync } from "node:fs"
import { dirname, isAbsolute } from "node:path"
import { fileURLToPath } from "node:url"

export const POLL_MS = 60_000
export const MAX_GH_FAILURES = 5
/** Marks the pipeline's own PR replies, so they never count as feedback. */
export const MARKER = "<!-- gated-dev -->"

export const EXIT = {
  feedback: 0,
  merged: 0,
  closed: 0,
  error: 1,
  usage: 2,
}

export function defaultRun(cmd, args, { cwd } = {}) {
  return new Promise((resolve, reject) => {
    execFile(cmd, args, { cwd, maxBuffer: 64 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        error.message = `${cmd} ${args.join(" ")} failed: ${stderr.trim() || error.message}`
        reject(error)
      } else resolve(stdout)
    })
  })
}

const defaultSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const time = (value) => {
  const t = Date.parse(value ?? "")
  return Number.isNaN(t) ? null : t
}

export function parsePrUrl(url) {
  const m = /^https?:\/\/[^/]+\/([^/]+)\/([^/]+)\/pull\/(\d+)/.exec(url ?? "")
  return m ? { owner: m[1], repo: m[2], number: Number(m[3]) } : null
}

/** Merges `gh pr view` JSON and inline comments into `{state, mergedAt, createdAt, feedback}`. */
export function normalizePr(view, inline = []) {
  const feedback = [
    ...(view.reviews ?? []).map((r) => ({
      login: r.author?.login ?? "",
      body: r.body ?? "",
      state: r.state ?? "",
      createdAt: r.submittedAt ?? r.createdAt,
    })),
    ...(view.comments ?? []).map((c) => ({
      login: c.author?.login ?? "",
      body: c.body ?? "",
      createdAt: c.createdAt,
    })),
    ...inline.map((c) => ({
      login: c.login ?? "",
      body: c.body ?? "",
      createdAt: c.createdAt,
    })),
  ]
  return {
    state: view.state,
    mergedAt: view.mergedAt ?? null,
    createdAt: view.createdAt,
    feedback,
  }
}

export async function fetchPr(url, run = defaultRun, cwd = process.cwd()) {
  const ref = parsePrUrl(url)
  if (!ref) throw new Error(`cannot parse PR url ${url}`)
  const view = JSON.parse(
    await run("gh", ["pr", "view", url, "--json", "state,mergedAt,createdAt,reviews,comments"], {
      cwd,
    }),
  )
  const out = await run(
    "gh",
    [
      "api",
      `repos/${ref.owner}/${ref.repo}/pulls/${ref.number}/comments`,
      "--paginate",
      "--jq",
      ".[] | {login: .user.login, body: .body, createdAt: .created_at}",
    ],
    { cwd },
  )
  const inline = out
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l))
  return normalizePr(view, inline)
}

/**
 * Newest human feedback after the cutoff, or null. Items are
 * `{login, body, state?, createdAt}`. Feedback: author not a bot, body without
 * the marker, created after the cutoff; a review counts when it has a body or
 * requests changes, a comment when it has a body.
 */
export function newestFeedbackAt(items, cutoff) {
  const after = time(cutoff) ?? -Infinity
  let newest = null
  for (const item of items ?? []) {
    if ((item.login ?? "").endsWith("[bot]")) continue
    const body = item.body ?? ""
    if (body.includes(MARKER)) continue
    const hasBody = body.trim() !== ""
    if (item.state !== undefined && item.state !== null) {
      if (!hasBody && item.state !== "CHANGES_REQUESTED") continue
    } else if (!hasBody) {
      continue
    }
    const at = time(item.createdAt)
    if (at === null || at <= after) continue
    if (newest === null || at > time(newest)) newest = item.createdAt
  }
  return newest
}

/** Cutoff: the last addressed comment, else the PR creation time. */
export function newFeedbackAt(pr, lastAddressedCommentAt) {
  return newestFeedbackAt(pr?.feedback, lastAddressedCommentAt ?? pr?.createdAt)
}

function readState(statePath) {
  let state
  try {
    state = JSON.parse(readFileSync(statePath, "utf8"))
  } catch (error) {
    throw new Error(`cannot read ${statePath}: ${error.message}`)
  }
  if (!state || typeof state !== "object" || Array.isArray(state)) {
    throw new Error(`${statePath} is not a state object`)
  }
  if (typeof state.prUrl !== "string" || state.prUrl === "") {
    throw new Error(`${statePath} has no prUrl`)
  }
  return state
}

/** Read-modify-write of state.json: only `watch` changes, atomically. */
function writeHeartbeat(statePath, watchField, pid) {
  const state = JSON.parse(readFileSync(statePath, "utf8"))
  const tmp = `${statePath}.${pid}.tmp`
  writeFileSync(tmp, `${JSON.stringify({ ...state, watch: watchField }, null, 2)}\n`)
  renameSync(tmp, statePath)
}

/**
 * Polls until feedback, merge, close or MAX_GH_FAILURES failures in a row.
 * Returns { outcome, prUrl, newestAt?, message?, at }.
 */
export async function watch({
  statePath,
  run = defaultRun,
  now = () => new Date(),
  sleep = defaultSleep,
  log = (line) => process.stderr.write(`${line}\n`),
  pid = process.pid,
}) {
  const startedAt = now().toISOString()
  let failures = 0
  let prUrl = null
  const done = (outcome, extra = {}) => ({ outcome, prUrl, ...extra, at: now().toISOString() })

  for (;;) {
    let pr = null
    let state = null
    let failure = null
    try {
      state = readState(statePath)
      prUrl = state.prUrl
      pr = await fetchPr(prUrl, run, dirname(statePath))
    } catch (error) {
      failure = error
    }

    // The watcher is alive even when the poll failed.
    try {
      writeHeartbeat(statePath, { pid, startedAt, heartbeatAt: now().toISOString() }, pid)
    } catch (error) {
      log(`heartbeat write failed: ${error.message}`)
    }

    if (!failure) {
      failures = 0
      if (pr.state === "MERGED") return done("merged")
      if (pr.state === "CLOSED") return done("closed")
      const newestAt = newFeedbackAt(pr, state.lastAddressedCommentAt)
      if (newestAt) return done("feedback", { newestAt })
    } else {
      failures += 1
      log(`poll failed (${failures}/${MAX_GH_FAILURES}): ${failure.message}`)
      if (failures >= MAX_GH_FAILURES) return done("error", { message: failure.message })
    }
    await sleep(POLL_MS)
  }
}

function parseArgs(argv) {
  if (argv.length !== 2 || argv[0] !== "--state") {
    return { error: "usage: watch-pr.mjs --state <abs path>/state.json" }
  }
  if (!isAbsolute(argv[1])) return { error: "--state must be an absolute path" }
  return { statePath: argv[1] }
}

/** Prints exactly one JSON line on stdout and returns the exit code. */
export async function main(argv, deps = {}) {
  const out = deps.out ?? ((line) => process.stdout.write(`${line}\n`))
  const parsed = parseArgs(argv)
  if (parsed.error) {
    out(JSON.stringify({ outcome: "usage", message: parsed.error }))
    return EXIT.usage
  }
  const result = await watch({ ...deps, statePath: parsed.statePath })
  out(JSON.stringify(result))
  return EXIT[result.outcome]
}

const isMain = (() => {
  try {
    return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))
  } catch {
    return false
  }
})()

if (isMain) process.exitCode = await main(process.argv.slice(2))
