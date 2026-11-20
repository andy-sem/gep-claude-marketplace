// Preload (node --import) for the watcher tests: every setTimeout fires at once, in order, and the
// requested delay is appended to the file named by GD_TEST_SLEEP_LOG (one number per line).
import { appendFileSync } from "node:fs"

const original = globalThis.setTimeout
globalThis.setTimeout = (fn, ms, ...args) => {
  const log = process.env.GD_TEST_SLEEP_LOG
  if (log) appendFileSync(log, `${ms}\n`)
  return original(fn, 0, ...args)
}
