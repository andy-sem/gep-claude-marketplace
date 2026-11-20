import { test } from "node:test"
import assert from "node:assert/strict"
import { readdirSync, readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const root = join(dirname(fileURLToPath(import.meta.url)), "..")
const readme = readFileSync(join(root, "README.md"), "utf8")

// Variables the hook wrapper and the tests use internally; not user settings.
const INTERNAL = new Set(["GATE_RUN", "GATE_DONE_FILE", "GATE_INFRA_NODE", "GATE_INFRA_PYTHON"])

function envNames() {
  const names = new Set()
  for (const dir of ["lib", "hooks"]) {
    for (const entry of readdirSync(join(root, dir), { withFileTypes: true })) {
      if (!entry.isFile()) continue
      const file = entry.name
      const text = readFileSync(join(root, dir, file), "utf8")
      for (const m of text.matchAll(/\b(?:GATE|TYPESAFE)_[A-Z_]*[A-Z]\b/g))
        if (!INTERNAL.has(m[0])) names.add(m[0])
    }
  }
  return [...names].sort()
}

test("README documents every env variable the gate reads", () => {
  const names = envNames()
  assert.ok(names.length > 10, "found the variables")
  const missing = names.filter((n) => !readme.includes(`\`${n}\``))
  assert.deepEqual(missing, [])
})

test("README lists every built-in pack and Jev prompt", () => {
  for (const dir of ["packs", "jev"]) {
    for (const file of readdirSync(join(root, dir))) {
      const name = file.replace(/\.json$/, "")
      assert.ok(readme.includes(`\`${name}\``), `${dir}/${file}`)
    }
  }
})
