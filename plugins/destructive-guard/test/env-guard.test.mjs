import { test } from "node:test"
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import { mkdtempSync, symlinkSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

const script = fileURLToPath(new URL("../hooks/env-guard.sh", import.meta.url))
const run = (tool_name, file_path, env = {}) =>
  spawnSync("bash", [script], {
    input: JSON.stringify({ tool_name, tool_input: { file_path } }),
    encoding: "utf8",
    env: { ...process.env, ...env },
  }).status

test("env guard blocks .env files for Read, Edit and Write", () => {
  for (const tool of ["Read", "Edit", "Write"]) {
    for (const f of ["/p/.env", "/p/.env.local", "/p/apps/web/.env.production"]) {
      assert.equal(run(tool, f), 2, `${tool} ${f}`)
    }
  }
})

test("env guard allows .env.example and ordinary files", () => {
  for (const f of ["/p/.env.example", "/p/src/index.ts", "/p/README.md", ""]) {
    assert.equal(run("Read", f), 0, f)
  }
})

test("env guard works without jq", () => {
  // A PATH holding only the tools the script needs, so jq cannot be found.
  const bin = mkdtempSync(join(tmpdir(), "env-guard-bin-"))
  for (const tool of ["cat", "sed", "head"]) {
    const found = spawnSync("bash", ["-c", `command -v ${tool}`], { encoding: "utf8" })
    symlinkSync(found.stdout.trim(), join(bin, tool))
  }
  const env = { PATH: bin }
  const status = (file_path) =>
    spawnSync("/bin/bash", [script], {
      input: JSON.stringify({ tool_name: "Read", tool_input: { file_path } }),
      encoding: "utf8",
      env,
    }).status
  assert.equal(status("/p/.env"), 2)
  assert.equal(status("/p/.env.example"), 0)
  assert.equal(status("/p/src/a.ts"), 0)
})
