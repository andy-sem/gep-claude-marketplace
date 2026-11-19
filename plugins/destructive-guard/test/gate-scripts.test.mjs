import { test } from "node:test"
import assert from "node:assert/strict"
import {
  mkdirSync,
  mkdtempSync,
  realpathSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { loadRules, RulesError } from "../lib/gate-engine.mjs"
import {
  collectScripts,
  findProjectRoot,
  globToRegExp,
  scanScripts,
} from "../lib/gate-scripts.mjs"

const here = dirname(fileURLToPath(import.meta.url))
const rules = loadRules(join(here, "fixtures", "rules.json"))

// A temporary project: an empty `.git` directory marks the root.
function project(files = {}) {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "gate-scripts-")))
  mkdirSync(join(root, ".git"))
  for (const [name, content] of Object.entries(files)) {
    mkdirSync(dirname(join(root, name)), { recursive: true })
    writeFileSync(join(root, name), content)
  }
  return root
}

const collect = (root, command, cwd = root) =>
  collectScripts(command, rules, { cwd, root })
const paths = (c) => c.files.map((f) => f.path)

test("findProjectRoot finds the .git ancestor, falling back to the env and the cwd", () => {
  const root = project({ "a/b/c.txt": "x" })
  assert.equal(findProjectRoot(join(root, "a/b")), root)
  const bare = realpathSync(mkdtempSync(join(tmpdir(), "gate-noroot-")))
  assert.equal(
    findProjectRoot(bare, { CLAUDE_PROJECT_DIR: root }),
    root,
    "env fallback",
  )
  assert.equal(findProjectRoot(bare, {}), bare, "cwd fallback")
})

test("shell scripts are found for every way of running them", () => {
  const root = project({
    "x.sh": "echo hi\n",
    "infra/cloud/apply.sh": "echo apply\n",
  })
  for (const command of [
    "bash x.sh",
    "sh x.sh --flag",
    "zsh -e x.sh",
    "bash -o pipefail x.sh",
    "./x.sh",
    "source x.sh",
    ". x.sh",
    "sudo env A=1 bash x.sh",
    "A=1 bash x.sh",
    "time bash ./x.sh",
    `bash ${join(root, "x.sh")}`,
  ]) {
    assert.deepEqual(paths(collect(root, command)), ["x.sh"], command)
  }
  assert.deepEqual(paths(collect(root, "infra/cloud/apply.sh --apply")), [
    "infra/cloud/apply.sh",
  ])
  assert.deepEqual(paths(collect(root, "cd infra/cloud && ./apply.sh")), [
    "infra/cloud/apply.sh",
  ])
  assert.deepEqual(paths(collect(root, "(cd infra/cloud; bash apply.sh)")), [
    "infra/cloud/apply.sh",
  ])
})

test("bash -c strings and stdin shells give no file", () => {
  const root = project({ "x.sh": "echo hi\n" })
  assert.deepEqual(paths(collect(root, "bash -c 'echo x'")), [])
  assert.deepEqual(paths(collect(root, "bash -c './x.sh'")), ["x.sh"])
})

test("a cd inside a subshell or a substitution does not move later commands; popd goes back", () => {
  const root = project({
    "infra/ok.sh": "echo ok\n",
    "infra/apply.sh": "terraform apply\n",
    "apply.sh": "echo top\n",
  })
  for (const command of [
    "(cd infra && bash ok.sh); bash infra/apply.sh",
    "pushd infra && bash ok.sh; popd; bash infra/apply.sh",
    "pushd infra > /dev/null; popd > /dev/null; bash infra/apply.sh",
    "echo $(cd infra); bash infra/apply.sh",
  ]) {
    assert.ok(paths(collect(root, command)).includes("infra/apply.sh"), command)
  }
  // the group leaves the directory unchanged: `apply.sh` is the top-level file
  assert.deepEqual(paths(collect(root, "(cd infra); bash apply.sh")), [
    "apply.sh",
  ])
  assert.deepEqual(
    paths(collect(root, "(cd infra) && cd infra && bash apply.sh")),
    ["infra/apply.sh"],
  )
  // separate groups do not share a directory
  assert.deepEqual(paths(collect(root, "(cd infra); (cd infra; bash ok.sh)")), [
    "infra/ok.sh",
  ])
  // inside the group the cd still applies, and nested cds stack
  assert.deepEqual(
    paths(collect(root, "(cd infra && (cd .. ; bash apply.sh))")),
    ["apply.sh"],
  )
})

test("a sourced file is resolved against the directory the script ran in", () => {
  const root = project({
    "infra/wrap.sh": "source ./inner.sh\n",
    "infra/inner.sh": "terraform apply\n",
    "infra/cloud/apply.sh": ". ./common.sh\n",
    "infra/cloud/common.sh": "terraform apply\n",
    "pkg/package.json": JSON.stringify({ scripts: { go: "bash go.sh" } }),
    "pkg/go.sh": "source ./helper.sh\n",
    "pkg/helper.sh": "terraform apply\n",
  })
  for (const [command, inner] of [
    ["cd infra && bash wrap.sh", "infra/inner.sh"],
    ["pushd infra && bash wrap.sh; popd", "infra/inner.sh"],
    ["(cd infra && bash wrap.sh)", "infra/inner.sh"],
    ["cd infra/cloud && ./apply.sh", "infra/cloud/common.sh"],
    ["pnpm -C pkg run go", "pkg/helper.sh"],
  ]) {
    assert.ok(paths(collect(root, command)).includes(inner), command)
  }
})

test("a cd after a shell string does not move the commands inside it", () => {
  const root = project({
    "infra/apply.sh": "terraform apply\n",
    "apply.sh": "echo top\n",
    "lib/x.txt": "",
  })
  for (const command of [
    "cd infra && sh -c './apply.sh' && cd ..",
    "cd infra && sh -c './apply.sh' && cd -",
    "cd infra && bash -c 'bash apply.sh'; cd ../lib",
  ]) {
    assert.deepEqual(paths(collect(root, command)), ["infra/apply.sh"], command)
  }
  assert.ok(
    paths(collect(root, "bash -c 'bash infra/apply.sh'; cd lib")).includes(
      "infra/apply.sh",
    ),
  )
  // a cd inside the string still applies inside it only
  assert.deepEqual(
    paths(collect(root, "sh -c 'cd infra && bash apply.sh'; bash apply.sh")),
    ["apply.sh", "infra/apply.sh"],
  )
})

test("shell strings given through wrappers and runners are followed", () => {
  const root = project({
    "infra/apply.sh": "terraform apply\n",
    "x.sh": "echo hi\n",
  })
  for (const command of [
    "watch bash infra/apply.sh",
    "watch -n 5 'bash infra/apply.sh'",
    "npx -c 'bash infra/apply.sh'",
    "npx --call 'bash infra/apply.sh'",
    "pnpm exec sh -c 'bash infra/apply.sh'",
    "timeout 5 bash -c 'bash infra/apply.sh'",
    "sudo -E sh -c 'cd infra && bash apply.sh'",
  ]) {
    assert.deepEqual(paths(collect(root, command)), ["infra/apply.sh"], command)
  }
  assert.deepEqual(paths(collect(root, "cd infra && watch bash apply.sh")), [
    "infra/apply.sh",
  ])
  // a string with an unresolvable expansion collects nothing
  assert.deepEqual(paths(collect(root, 'watch "bash $X"')), [])
  // the same file reached twice is collected once
  assert.deepEqual(paths(collect(root, "bash -c 'bash x.sh'; bash x.sh")), [
    "x.sh",
  ])
})

test("node targets: files, preloads, --test and --run", () => {
  const root = project({
    "a.mjs": "",
    "b.mjs": "",
    "pre.cjs": "",
    "t.test.mjs": "",
    "package.json": JSON.stringify({ scripts: { go: "echo go" } }),
  })
  assert.deepEqual(paths(collect(root, "node a.mjs")), ["a.mjs"])
  assert.deepEqual(
    paths(collect(root, "node --max-old-space-size=4096 a.mjs")),
    ["a.mjs"],
  )
  assert.deepEqual(paths(collect(root, "node -C dev a.mjs b.mjs")), ["a.mjs"])
  assert.deepEqual(paths(collect(root, "node -r ./pre.cjs a.mjs")), [
    "pre.cjs",
    "a.mjs",
  ])
  assert.deepEqual(paths(collect(root, "node --import ./pre.cjs a.mjs")), [
    "pre.cjs",
    "a.mjs",
  ])
  assert.deepEqual(paths(collect(root, "node -e 'console.log(1)'")), [])
  assert.deepEqual(paths(collect(root, "node -p 1")), [])
  assert.deepEqual(paths(collect(root, "node --eval 1")), [])
  assert.deepEqual(paths(collect(root, "node --test a.mjs b.mjs")), [
    "a.mjs",
    "b.mjs",
  ])
  assert.deepEqual(
    paths(collect(root, 'node --test ".claude/hooks/*.test.mjs"')),
    [],
  )
  assert.deepEqual(paths(collect(root, "node --run go")), [
    "package.json#scripts.go",
  ])
})

test("python, tsx and deno targets", () => {
  const root = project({ "a.py": "", "b.ts": "", "c.ts": "" })
  assert.deepEqual(paths(collect(root, "python a.py")), ["a.py"])
  assert.deepEqual(paths(collect(root, "python3 -u a.py")), ["a.py"])
  assert.deepEqual(paths(collect(root, "python3.12 -W ignore a.py")), ["a.py"])
  assert.deepEqual(paths(collect(root, "python3 -m http.server")), [])
  assert.deepEqual(paths(collect(root, "python3 -c 'print(1)'")), [])
  assert.deepEqual(paths(collect(root, "tsx b.ts")), ["b.ts"])
  assert.deepEqual(paths(collect(root, "tsx watch b.ts")), ["b.ts"])
  assert.deepEqual(paths(collect(root, "pnpm exec tsx b.ts")), ["b.ts"])
  assert.deepEqual(paths(collect(root, "npx tsx c.ts")), ["c.ts"])
  assert.deepEqual(paths(collect(root, "deno run --allow-read b.ts")), ["b.ts"])
  assert.deepEqual(paths(collect(root, "deno test")), [])
})

test("package scripts resolve from package.json in the cwd or -C/--dir/--prefix/--cwd", () => {
  const root = project({
    "package.json": JSON.stringify({
      scripts: { build: "turbo build", "db:x": "node scripts/a.mjs" },
    }),
    "apps/web/package.json": JSON.stringify({ scripts: { dev: "vite dev" } }),
    "scripts/a.mjs": "console.log(1)\n",
  })
  const one = (c) => paths(collect(root, c))
  assert.deepEqual(one("pnpm run build"), ["package.json#scripts.build"])
  assert.deepEqual(one("npm run-script build"), ["package.json#scripts.build"])
  assert.deepEqual(one("yarn run build"), ["package.json#scripts.build"])
  assert.deepEqual(one("bun run build"), ["package.json#scripts.build"])
  assert.deepEqual(one("pnpm build"), ["package.json#scripts.build"])
  assert.deepEqual(one("yarn build"), ["package.json#scripts.build"])
  assert.deepEqual(one("npm build"), [])
  assert.deepEqual(one("pnpm install"), [])
  assert.deepEqual(one("pnpm -C apps/web dev"), [
    "apps/web/package.json#scripts.dev",
  ])
  assert.deepEqual(one("pnpm --dir apps/web run dev"), [
    "apps/web/package.json#scripts.dev",
  ])
  assert.deepEqual(one("npm --prefix apps/web run dev"), [
    "apps/web/package.json#scripts.dev",
  ])
  assert.deepEqual(one("yarn --cwd apps/web run dev"), [
    "apps/web/package.json#scripts.dev",
  ])
  assert.deepEqual(one("pnpm missing"), [])
  // the commands in a script body are followed
  assert.deepEqual(one("pnpm db:x"), [
    "package.json#scripts.db:x",
    "scripts/a.mjs",
  ])
  const test = project({
    "package.json": JSON.stringify({ scripts: { test: "node --test" } }),
  })
  assert.deepEqual(paths(collect(test, "npm test")), [
    "package.json#scripts.test",
  ])
})

test("gh workflow run resolves a file name or a workflow name", () => {
  const root = project({
    ".github/workflows/deploy.yml": "name: Deploy Cloud\non: workflow_dispatch\n",
    ".github/workflows/other.yaml": "name: Other\n",
  })
  const one = (c) => paths(collect(root, c))
  assert.deepEqual(one("gh workflow run deploy.yml"), [
    ".github/workflows/deploy.yml",
  ])
  assert.deepEqual(one("gh workflow run deploy.yml -f env=dev --ref main"), [
    ".github/workflows/deploy.yml",
  ])
  assert.deepEqual(one("gh workflow run -r main other.yaml"), [
    ".github/workflows/other.yaml",
  ])
  assert.deepEqual(one('gh workflow run "Deploy Cloud"'), [
    ".github/workflows/deploy.yml",
  ])
  assert.deepEqual(one("gh workflow run 12345"), [])
  assert.deepEqual(one("gh workflow run nothing.yml"), [])
  assert.deepEqual(one("gh workflow list"), [])
})

test("source and import following: resolution, extensions, depth, cycles", () => {
  const root = project({
    "run.sh": [
      "#!/bin/bash",
      'source "$(dirname "$0")/lib/a.sh"',
      '. "${BASH_SOURCE%/*}/lib/b.sh"',
      "if true; then source lib/c.sh; fi",
      'source "$X/skip.sh"',
      "",
    ].join("\n"),
    "lib/a.sh": "echo a\n",
    "lib/b.sh": "echo b\n",
    "lib/c.sh": "echo c\n",
    "main.mjs": [
      'import { a } from "./m/a.mjs"',
      'import "./m/side.js"',
      'export * from "./m/ex"',
      'const x = await import("./m/dyn.ts")',
      'const y = require("./m/req.cjs")',
      'import fs from "node:fs"',
      'import z from "left-pad"',
      "import {",
      "  multi,",
      '} from "./m/multi.mjs"',
      "",
    ].join("\n"),
    "m/a.mjs": 'import "../chain/one.mjs"\n',
    "m/side.js": "",
    "m/ex.ts": "",
    "m/dyn.ts": "",
    "m/req.cjs": "",
    "m/multi.mjs": "",
    "chain/one.mjs": 'import "./two.mjs"\n',
    "chain/two.mjs": 'import "./three.mjs"\n',
    "chain/three.mjs": 'import "./four.mjs"\n',
    "chain/four.mjs": "",
    "idx/main.mjs": 'import "./lib"\n',
    "idx/lib/index.mjs": "",
    "cyc/a.mjs": 'import "./b.mjs"\n',
    "cyc/b.mjs": 'import "./a.mjs"\n',
  })
  assert.deepEqual(paths(collect(root, "bash run.sh")), [
    "run.sh",
    "lib/a.sh",
    "lib/b.sh",
    "lib/c.sh",
  ])
  const main = collect(root, "node main.mjs")
  assert.deepEqual(paths(main), [
    "main.mjs",
    "m/a.mjs",
    "m/side.js",
    "m/ex.ts",
    "m/dyn.ts",
    "m/req.cjs",
    "m/multi.mjs",
    "chain/one.mjs",
    "chain/two.mjs",
  ])
  assert.deepEqual(
    main.files.map((f) => f.depth),
    [0, 1, 1, 1, 1, 1, 1, 2, 3],
  )
  // depth 3 is the last level that is read
  assert.deepEqual(paths(collect(root, "node chain/one.mjs")), [
    "chain/one.mjs",
    "chain/two.mjs",
    "chain/three.mjs",
    "chain/four.mjs",
  ])
  assert.deepEqual(paths(collect(root, "node chain/two.mjs")), [
    "chain/two.mjs",
    "chain/three.mjs",
    "chain/four.mjs",
  ])
  assert.deepEqual(paths(collect(root, "node idx/main.mjs")), [
    "idx/main.mjs",
    "idx/lib/index.mjs",
  ])
  assert.deepEqual(paths(collect(root, "node cyc/a.mjs")), [
    "cyc/a.mjs",
    "cyc/b.mjs",
  ])
})

test("a script that sources $SCRIPT_DIR/x resolves it against the script", () => {
  const root = project({
    "tools/run.sh":
      'source "$SCRIPT_DIR/helper.sh"\nsource ${SCRIPT_DIR}/two.sh\n',
    "tools/helper.sh": "",
    "tools/two.sh": "",
  })
  assert.deepEqual(paths(collect(root, "bash tools/run.sh")), [
    "tools/run.sh",
    "tools/helper.sh",
    "tools/two.sh",
  ])
})

test("the 64 KB per-file cut is kept and reported as a problem", () => {
  const root = project({ "big.mjs": `// ${"x".repeat(70000)}\ncloudctl\n` })
  const c = collect(root, "node big.mjs")
  assert.equal(c.files.length, 1)
  assert.equal(c.files[0].truncated, true)
  assert.equal(c.files[0].content.length, 65536)
  assert.equal(c.files[0].size > 65536, true)
  assert.deepEqual(c.problems, [
    { path: "big.mjs", reason: "exceeds 64 KB", exempt: false },
  ])
  assert.equal(scanScripts(c, rules).reason, "script: big.mjs exceeds 64 KB")
})

test("more than 32 files stops following and is a problem", () => {
  const files = { "m0.mjs": "" }
  let imports = ""
  for (let i = 1; i <= 40; i++) {
    files[`m${i}.mjs`] = ""
    imports += `import "./m${i}.mjs"\n`
  }
  files["m0.mjs"] = imports
  const root = project(files)
  const c = collect(root, "node m0.mjs")
  assert.equal(c.files.length, 32)
  assert.deepEqual(
    c.problems.map((p) => p.reason),
    ["more than 32 files"],
  )
})

test("files outside the project, symlinks out and non-regular files are problems", () => {
  const outside = realpathSync(mkdtempSync(join(tmpdir(), "gate-outside-")))
  writeFileSync(join(outside, "x.sh"), "echo\n")
  const root = project({ "dir/keep": "" })
  symlinkSync(join(outside, "x.sh"), join(root, "link.sh"))
  const reasons = (command) =>
    collect(root, command).problems.map((p) => `${p.path} ${p.reason}`)
  assert.deepEqual(reasons(`bash ${join(outside, "x.sh")}`), [
    `${join(outside, "x.sh")} is outside the project`,
  ])
  assert.deepEqual(reasons("bash link.sh"), ["link.sh is outside the project"])
  assert.deepEqual(reasons("bash dir"), ["dir is not a regular file"])
  // an absolute path outside the project that is a command word is a system program
  assert.deepEqual(reasons(`${join(outside, "x.sh")} --flag`), [])
  assert.deepEqual(collect(root, "/usr/bin/env true").problems, [])
})

test("missing, glob and dynamic paths are skipped", () => {
  const root = project({ "a.sh": "" })
  for (const command of [
    "bash missing.sh",
    "bash a-*.sh",
    "bash $SCRIPT",
    "bash $(echo a).sh",
    'bash "${DIR}/a.sh"',
    "node ~/x.mjs",
    "cd $X && bash a.sh",
    "cd missing && bash a.sh",
  ]) {
    const c = collect(root, command)
    assert.deepEqual(c.files, [], command)
    assert.deepEqual(c.problems, [], command)
  }
})

test("an unparsable command collects nothing", () => {
  const root = project({ "a.sh": "" })
  assert.deepEqual(collect(root, 'bash "a.sh'), { files: [], problems: [] })
})

test("scanScripts: program names, patterns and reasons", () => {
  const root = project({
    "tf.sh": "terraform -chdir=infra apply\n",
    "tofu.sh": "# plain\ntofu import a b\n",
    "g.sh": "echo cloudctl-like\n/usr/bin/cloudctl run deploy\n",
    "ref.mjs": 'fetch("https://run.acmecloudapis.com/v2/x")\n',
    "sup.mjs": 'import { createClient } from "@dbhost/dbhost-js"\n',
    "pg.mjs": 'const u = "postgresql://u@h/db"\n',
    "gh.mjs": 'const a = "acmecloud-github-actions/auth"\n',
    "words.sh": "echo terraformer my-psql psqlx a.dwh\n",
    "cf.mjs":
      'await $`wrangler deploy`\nfetch("https://api.cloudflare.com/x")\n',
    "ssr.mjs": 'import x from "@dbhost/ssr"\n',
  })
  const reason = (command) =>
    scanScripts(collect(root, command), rules)?.reason ?? null
  assert.equal(reason("bash tf.sh"), "script: tf.sh runs terraform")
  assert.equal(reason("bash tofu.sh"), "script: tofu.sh runs tofu")
  assert.equal(reason("bash g.sh"), "script: g.sh runs cloudctl")
  assert.match(
    reason("node ref.mjs"),
    /^script: ref\.mjs references acmecloudapis/,
  )
  assert.match(reason("node sup.mjs"), /^script: sup\.mjs references @dbhost/)
  assert.match(reason("node pg.mjs"), /^script: pg\.mjs references postgres/)
  assert.match(
    reason("node gh.mjs"),
    /^script: gh\.mjs references acmecloud-github/,
  )
  assert.equal(reason("bash words.sh"), null)
  assert.equal(reason("node cf.mjs"), null)
  assert.equal(reason("node ssr.mjs"), null)
  assert.equal(scanScripts({ files: [], problems: [] }, rules), null)
  assert.equal(scanScripts(undefined, rules), null)
})

test("scanScripts: a workflow with a Acmecloud Actions step asks", () => {
  const root = project({
    ".github/workflows/deploy.yml": [
      "name: Deploy",
      "jobs:",
      "  d:",
      "    steps:",
      "      - uses: acmecloud-github-actions/auth@v2",
      "",
    ].join("\n"),
  })
  const reason = scanScripts(collect(root, "gh workflow run deploy.yml"), rules)
  assert.match(
    reason.reason,
    /^script: \.github\/workflows\/deploy\.yml references/,
  )
})

test("scanScripts: a package script body that runs a gated program asks", () => {
  const root = project({
    "package.json": JSON.stringify({
      scripts: { push: "dbhost db push", hi: "echo hi" },
    }),
  })
  assert.equal(
    scanScripts(collect(root, "pnpm push"), rules).reason,
    "script: package.json#scripts.push runs dbhost",
  )
  assert.equal(scanScripts(collect(root, "pnpm hi"), rules), null)
})

test("exempt test files and their imports are not scanned", () => {
  const root = project({
    "scripts/a.test.mjs": 'import "./runner.mjs"\n',
    "scripts/runner.mjs": 'spawn("terraform", ["apply"])\n',
    "scripts/other.mjs": 'spawn("terraform", ["apply"])\n',
    "scripts/ticket-flow/deep/x.test.mjs": 'import "../../other.mjs"\n',
    ".claude/hooks/h.test.mjs": "terraform apply\n",
    "scripts/sub/c.test.mjs": "terraform apply\n",
  })
  const run = (command) => {
    const c = collect(root, command)
    return { c, hit: scanScripts(c, rules)?.reason ?? null }
  }
  const a = run("node scripts/a.test.mjs")
  assert.deepEqual(paths(a.c), ["scripts/a.test.mjs", "scripts/runner.mjs"])
  assert.equal(a.c.files[1].exempt, true)
  assert.equal(a.hit, null)
  assert.equal(run("node scripts/ticket-flow/deep/x.test.mjs").hit, null)
  assert.equal(run("node --test .claude/hooks/h.test.mjs").hit, null)
  assert.equal(
    run("node scripts/other.mjs").hit,
    "script: scripts/other.mjs runs terraform",
  )
  // `scripts/*.test.mjs` does not cover nested directories
  assert.equal(
    run("node scripts/sub/c.test.mjs").hit,
    "script: scripts/sub/c.test.mjs runs terraform",
  )
})

test("an exempt file that is too large does not ask", () => {
  const root = project({
    "scripts/big.test.mjs": "x".repeat(70000),
  })
  assert.equal(
    scanScripts(collect(root, "node scripts/big.test.mjs"), rules),
    null,
  )
})

test("globToRegExp supports **/, **, * and ?", () => {
  assert.equal(globToRegExp("a/**/b.js").test("a/b.js"), true)
  assert.equal(globToRegExp("a/**/b.js").test("a/x/y/b.js"), true)
  assert.equal(globToRegExp("a/*.js").test("a/x/b.js"), false)
  assert.equal(globToRegExp("a/*.js").test("a/b.js"), true)
  assert.equal(globToRegExp("a/?.js").test("a/b.js"), true)
  assert.equal(globToRegExp("a/?.js").test("a/bc.js"), false)
  assert.equal(globToRegExp("a/**").test("a/x/y"), true)
  assert.equal(globToRegExp("a.b").test("axb"), false)
})

test("loadRules validates scriptPatterns and scriptScanExempt", () => {
  const dir = mkdtempSync(join(tmpdir(), "gate-script-rules-"))
  const p = join(dir, "r.json")
  const load = (extra) => {
    writeFileSync(p, JSON.stringify(extra))
    return loadRules(p)
  }
  assert.throws(() => load({ scriptPatterns: ["("] }), RulesError)
  assert.throws(() => load({ scriptPatterns: [1] }), RulesError)
  assert.throws(() => load({ scriptPatterns: "x" }), RulesError)
  assert.throws(() => load({ scriptScanExempt: [1] }), RulesError)
  assert.throws(() => load({ scriptScanExempt: [""] }), RulesError)
  assert.throws(() => load({ scriptScanExempt: "x" }), RulesError)
  const ok = load({ scriptPatterns: ["a+b"], scriptScanExempt: ["x/*.js"] })
  assert.equal(ok.scriptPatterns[0].test("aab"), true)
  assert.deepEqual(ok.scriptScanExempt, ["x/*.js"])
  assert.deepEqual(load({}).scriptPatterns, [])
  assert.deepEqual(load({}).scriptScanExempt, [])
  // the shipped file carries the spec values
  assert.equal(rules.scriptPatterns.length, 9)
  assert.deepEqual(rules.scriptScanExempt, [
    ".claude/hooks/*.test.mjs",
    "scripts/*.test.mjs",
    "scripts/ticket-flow/**/*.test.mjs",
  ])
})

test("terraform test sends the root module's and the test directory's *.tftest.hcl as exempt context", () => {
  const env = "infra/cloud/environments/preview-x"
  const root = project({
    [`${env}/main.tf`]: 'provider "acmecloud" {}\n',
    [`${env}/root.tftest.hcl`]: "# runs cloudctl and terraform apply\nrun {}\n",
    [`${env}/tests/b.tftest.hcl`]: 'mock_provider "acmecloud" {}\n',
    [`${env}/tests/a.tftest.hcl`]: 'mock_provider "acmecloud" {}\n',
    [`${env}/tests/notes.md`]: "x\n",
    [`${env}/other/c.tftest.hcl`]: "run {}\n",
  })
  const expected = [
    `${env}/root.tftest.hcl`,
    `${env}/tests/a.tftest.hcl`,
    `${env}/tests/b.tftest.hcl`,
  ]
  for (const command of [
    `cd ${env} && terraform test`,
    `terraform -chdir=${env} test`,
    `tofu -chdir=${env} test -verbose`,
    `docker run --rm -w ${join(root, env)} --entrypoint terraform hashicorp/terraform:1.17.0 test`,
    `D=${root}; P=$D/${env}; docker run --rm --workdir=\${P} --entrypoint terraform img test`,
  ]) {
    const c = collect(root, command)
    assert.deepEqual(paths(c), expected, command)
    assert.ok(
      c.files.every((f) => f.exempt),
      `${command}: context files are exempt`,
    )
  }
  assert.deepEqual(
    paths(collect(root, `terraform -chdir=${env} test -test-directory=other`)),
    [`${env}/root.tftest.hcl`, `${env}/other/c.tftest.hcl`],
  )
  // a test file that names a gated program does not ask through the script scan
  assert.equal(
    scanScripts(collect(root, `cd ${env} && terraform test`), rules),
    null,
  )
})

test("terraform test sends nothing when the directory is unknown or not local", () => {
  const env = "infra/cloud/environments/preview-x"
  const root = project({ [`${env}/tests/a.tftest.hcl`]: "run {}\n" })
  for (const command of [
    `cd ${env} && terraform plan`,
    `cd ${env} && terraform validate`,
    `terraform -chdir=$X test`,
    `cd $X && terraform test`,
    `docker run --rm -w $X --entrypoint terraform img test`,
    `cd ${env} && docker run --rm --entrypoint terraform img test`,
    `cd ${env} && docker run --rm -w tests --entrypoint terraform img test`,
    `cd ${env} && ssh host terraform test`,
    `(P=${join(root, env)}); docker run -w $P --entrypoint terraform img test`,
  ]) {
    assert.deepEqual(paths(collect(root, command)), [], command)
  }
})

test("variables assigned earlier in the command resolve script paths", () => {
  const root = project({ "infra/apply.sh": "echo apply\n" })
  for (const command of [
    "S=infra/apply.sh; bash $S",
    "D=infra; S=${D}/apply.sh; bash $S",
    "D=infra\ncd $D && ./apply.sh",
  ]) {
    assert.deepEqual(paths(collect(root, command)), ["infra/apply.sh"], command)
  }
  // a prefix assignment applies to its own command only
  assert.deepEqual(paths(collect(root, "S=infra/apply.sh true; bash $S")), [])
})
