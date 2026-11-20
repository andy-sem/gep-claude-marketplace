// Calls one export of a destructive-guard lib module and prints the result as JSON.
//   node _bridge.mjs <module> <export>     (JSON array of arguments on stdin)
// <module> is a file name without extension under plugins/destructive-guard/lib/.
// A function export is called with the arguments and awaited; any other export is
// returned as is (arguments must be []). A thrown error exits 1 with
// {"$error": {"name", "message"}} on stdout.

import { dirname, join } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const LIB = join(dirname(fileURLToPath(import.meta.url)), "..", "plugins", "destructive-guard", "lib")

function replacer(_key, value) {
  if (value === undefined) return null
  if (value instanceof Set) return [...value]
  if (value instanceof Map) return Object.fromEntries(value)
  if (value instanceof RegExp) return { $regexp: value.source, flags: value.flags }
  return value
}

async function readStdin() {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  return Buffer.concat(chunks).toString("utf8")
}

try {
  const [moduleName, exportName] = process.argv.slice(2)
  if (!moduleName || !exportName) throw new Error("usage: _bridge.mjs <module> <export>")
  const raw = await readStdin()
  const args = raw.trim() ? JSON.parse(raw) : []
  const mod = await import(pathToFileURL(join(LIB, `${moduleName}.mjs`)).href)
  if (!(exportName in mod)) throw new Error(`${moduleName}.mjs has no export "${exportName}"`)
  const target = mod[exportName]
  const result = typeof target === "function" ? await target(...args) : target
  process.stdout.write(JSON.stringify(result, replacer) ?? "null")
} catch (e) {
  process.stdout.write(JSON.stringify({ $error: { name: e?.name ?? "Error", message: e?.message ?? String(e) } }))
  process.exitCode = 1
}
