// Calls one export of a destructive-guard lib module and prints the result as JSON.
//   node _bridge.mjs <module> <export>     (JSON array of arguments on stdin)
//   node _bridge.mjs --batch               (stdin: JSON list of [module, export, args]; results in order)
// A {"$call": [module, export, args]} marker anywhere in the arguments is replaced by the
// awaited result of that call. In batch mode an error also carries the failing "index".
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

async function invoke(moduleName, exportName, args) {
  const mod = await import(pathToFileURL(join(LIB, `${moduleName}.mjs`)).href)
  if (!(exportName in mod)) throw new Error(`${moduleName}.mjs has no export "${exportName}"`)
  const target = mod[exportName]
  return typeof target === "function" ? await target(...args) : target
}

// Replaces {"$call": [module, export, args]} markers anywhere in a value (depth-first)
// by the awaited result of that call.
async function resolve(value) {
  if (Array.isArray(value)) {
    const out = []
    for (const item of value) out.push(await resolve(item))
    return out
  }
  if (value && typeof value === "object") {
    if (Array.isArray(value.$call)) {
      const [m, f, a] = value.$call
      return invoke(m, f, await resolve(a ?? []))
    }
    const out = {}
    for (const [k, v] of Object.entries(value)) out[k] = await resolve(v)
    return out
  }
  return value
}

let index = null
try {
  const [first, second] = process.argv.slice(2)
  const raw = await readStdin()
  const parsed = raw.trim() ? JSON.parse(raw) : []
  let result
  if (first === "--batch") {
    result = []
    for (index = 0; index < parsed.length; index++) {
      const [m, f, a] = parsed[index]
      result.push(await invoke(m, f, await resolve(a ?? [])))
    }
    index = null
  } else {
    if (!first || !second) throw new Error("usage: _bridge.mjs <module> <export> | --batch")
    result = await invoke(first, second, await resolve(parsed))
  }
  process.stdout.write(JSON.stringify(result, replacer) ?? "null")
} catch (e) {
  const error = { name: e?.name ?? "Error", message: e?.message ?? String(e) }
  if (index !== null) error.index = index
  process.stdout.write(JSON.stringify({ $error: error }))
  process.exitCode = 1
}
