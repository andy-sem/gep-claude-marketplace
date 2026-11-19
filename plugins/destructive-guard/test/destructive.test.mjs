import { test } from "node:test"
import assert from "node:assert/strict"
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import {
  RulesError,
  classify,
  gate,
  loadPacks,
  packPath,
  parseRules,
} from "../lib/gate-engine.mjs"

const rules = loadPacks(["base", "destructive"].map(packPath))
const bash = (command) => ({ tool_name: "Bash", tool_input: { command } })
const mcp = (tool_name, tool_input = {}) => ({ tool_name, tool_input })
const idOf = (input) => classify(input, rules)?.reason.split(":")[0] ?? null

// [input, expected rule id or null]
const cases = [
  // filesystem
  [bash("rm -rf build"), "rm-recursive-force"],
  [bash("rm -fr build"), "rm-recursive-force"],
  [bash("rm -r -f build"), "rm-recursive-force"],
  [bash("rm -Rf build"), "rm-recursive-force"],
  [bash("rm --recursive --force build"), "rm-recursive-force"],
  [bash("sudo rm -rf /var/x"), "rm-recursive-force"],
  [bash("/bin/rm -rf x"), "rm-recursive-force"],
  [bash("rm -rf $DIR"), "rm-recursive-force"],
  [bash("find . -name '*.tmp' -exec rm -rf {} +"), "rm-recursive-force"],
  [bash("ls | xargs rm -rf"), "rm-recursive-force"],
  [bash("cd x && rm -rf y"), "rm-recursive-force"],
  [bash("bash -c 'rm -rf y'"), "rm-recursive-force"],
  [bash("rm file.txt"), null],
  [bash("rm -f file.txt"), null],
  [bash("rm -r dir"), null],
  [bash("rm -i -r dir"), null],
  [bash("rm -- -rf"), null],
  [bash("find . -name '*.tmp' -delete"), "find-delete"],
  [bash("find . -name '*.tmp'"), null],
  [bash("find . -name delete"), null],
  [bash("shred -u secret.txt"), "shred"],
  [bash("dd if=/dev/zero of=/dev/disk2 bs=1m"), "dd-output"],
  [bash("dd if=/dev/disk2 bs=1m count=1"), null],
  [bash("mkfs.ext4 /dev/sdb1"), "mkfs"],
  [bash("truncate -s 0 app.log"), "truncate"],
  [bash("diskutil eraseDisk APFS X disk2"), "diskutil-erase"],
  [bash("diskutil apfs deleteVolume disk3s2"), "diskutil-erase"],
  [bash("diskutil list"), null],
  // git
  [bash("git push --force"), "git-push-force"],
  [bash("git push -f origin main"), "git-push-force"],
  [bash("git push -fu origin main"), "git-push-force"],
  [bash("git push --force-with-lease"), "git-push-force"],
  [bash("git push --force-with-lease=main:abc origin main"), "git-push-force"],
  [bash("git push --mirror"), "git-push-force"],
  [bash("git push origin --delete feature"), "git-push-force"],
  [bash("git push -d origin feature"), "git-push-force"],
  [bash("git -C repo push -f"), "git-push-force"],
  [bash("git push origin +main"), "git-push-refspec"],
  [bash("git push origin :feature"), "git-push-refspec"],
  [bash("git push"), null],
  [bash("git push -u origin feature"), null],
  [bash("git push origin HEAD:refs/heads/feature"), null],
  [bash("git push --help"), null],
  [bash("git reset --hard HEAD~1"), "git-reset-hard"],
  [bash("git reset --soft HEAD~1"), null],
  [bash("git reset HEAD file"), null],
  [bash("git clean -fdx"), "git-clean"],
  [bash("git clean -f"), "git-clean"],
  [bash("git clean --force -d"), "git-clean"],
  [bash("git clean -n"), null],
  [bash("git clean -nfd"), null],
  [bash("git clean --dry-run -f"), null],
  [bash("git branch -D feature"), "git-branch-force-delete"],
  [bash("git branch -d feature"), null],
  [bash("git branch -a"), null],
  [bash("git checkout -- ."), "git-checkout-all"],
  [bash("git checkout ."), "git-checkout-all"],
  [bash("git checkout main"), null],
  [bash("git checkout -- src/a.ts"), null],
  [bash("git restore ."), "git-restore-all"],
  [bash("git restore --staged ."), null],
  [bash("git restore src/a.ts"), null],
  [bash("git stash drop"), "git-stash-drop"],
  [bash("git stash clear"), "git-stash-drop"],
  [bash("git stash"), null],
  [bash("git stash pop"), null],
  [bash("git filter-branch --tree-filter x HEAD"), "git-history-rewrite"],
  [bash("git filter-repo --path x"), "git-history-rewrite"],
  [bash("git update-ref -d refs/heads/x"), "git-update-ref-delete"],
  [bash("git update-ref refs/heads/x abc"), null],
  [bash("git status"), null],
  [bash("git log --oneline -5"), null],
  [bash("git commit -m 'remove rm -rf from scripts'"), null],
  [bash("git commit -m 'git push --force fix'"), null],
  // gh
  [bash("gh repo delete me/x --yes"), "gh-delete"],
  [bash("gh release delete v1"), "gh-delete"],
  [bash("gh secret delete TOKEN"), "gh-delete"],
  [bash("gh pr close 12 --delete-branch"), "gh-pr-delete-branch"],
  [bash("gh pr merge 12 --squash -d"), "gh-pr-delete-branch"],
  [bash("gh api -X DELETE repos/me/x"), "gh-api-delete"],
  [bash("gh api --method=DELETE repos/me/x"), "gh-api-delete"],
  [bash("gh api repos/me/x"), null],
  [bash("gh pr close 12"), null],
  [bash("gh pr merge 12 --squash"), null],
  [bash("gh repo view"), null],
  // infra
  [bash("terraform destroy"), "terraform-destroy"],
  [bash("tofu state rm a.b"), "terraform-destroy"],
  [bash("terraform apply -destroy"), "terraform-apply-destroy"],
  [bash("terraform apply"), null],
  [bash("terraform plan"), null],
  [bash("terraform destroy -help"), null],
  [bash("kubectl delete pod x"), "kubectl-delete"],
  [bash("kubectl -n prod delete deploy api"), "kubectl-delete"],
  [bash("kubectl drain node-1"), "kubectl-delete"],
  [bash("kubectl get pods"), null],
  [bash("kubectl apply -f x.yaml"), null],
  [bash("helm uninstall api"), "helm-uninstall"],
  [bash("helm list"), null],
  [bash("docker system prune -af"), "docker-prune"],
  [bash("docker volume rm data"), "docker-prune"],
  [bash("docker volume prune"), "docker-prune"],
  [bash("docker compose down -v"), "docker-compose-volumes"],
  [bash("docker compose down"), null],
  [bash("docker ps"), null],
  [bash("docker rm abc"), null],
  // cloud CLIs
  [bash("aws ec2 terminate-instances --instance-ids i-1"), "aws-delete"],
  [bash("aws dynamodb delete-table --table-name t"), "aws-delete"],
  [bash("aws s3 rm s3://b/k --recursive"), "aws-s3-delete"],
  [bash("aws s3 rb s3://b"), "aws-s3-delete"],
  [bash("aws s3 ls s3://b"), null],
  [bash("aws s3 cp delete-me.txt s3://b/"), null],
  [bash("aws ec2 describe-instances"), null],
  [bash("az group delete -n rg"), "az-delete"],
  [bash("az group list"), null],
  [bash("wrangler kv namespace delete --namespace-id x"), "wrangler-delete"],
  [bash("wrangler deploy"), null],
  // SQL content
  [bash('psql -c "DROP TABLE users"'), "sql-destructive"],
  [bash("psql -c 'drop schema public cascade'"), "sql-destructive"],
  [bash("psql --command='TRUNCATE users'"), "sql-destructive"],
  [bash('psql -c "DELETE FROM users"'), "sql-destructive"],
  [bash('psql -c "ALTER TABLE users DROP COLUMN email"'), "sql-destructive"],
  [bash("mysql -e 'DROP DATABASE app'"), "sql-destructive"],
  [bash('sqlite3 app.db "DELETE FROM t"'), "sql-destructive"],
  [bash("psql app <<'SQL'\nDROP TABLE t;\nSQL"), "sql-destructive"],
  [bash('psql -c "DELETE FROM users WHERE id = 1"'), null],
  [bash('psql -c "SELECT * FROM drop_log"'), null],
  [bash('psql -c "SELECT 1"'), null],
  [bash("psql app <<'SQL'\nSELECT 1;\nSQL"), null],
  [bash('wrangler d1 execute db --command "DROP TABLE t"'), "wrangler-d1-sql"],
  [bash('wrangler d1 execute db --command "SELECT 1"'), null],
  // MCP
  [mcp("mcp__github__delete_file"), "mcp-destructive-tool"],
  [mcp("mcp__db__drop_table"), "mcp-destructive-tool"],
  [mcp("mcp__plugin_x_x__reset_branch"), "mcp-destructive-tool"],
  [mcp("mcp__plugin_atlassian_atlassian__executeDestructive"), "mcp-destructive-tool"],
  [mcp("mcp__x__deleteIssue"), "mcp-destructive-tool"],
  [mcp("mcp__x__select_dropdown_option"), null],
  [mcp("mcp__x__list_tables"), null],
  [mcp("mcp__plugin_atlassian_atlassian__editJiraIssue"), null],
  [mcp("mcp__db__execute_sql", { query: "DROP TABLE users" }), "mcp-destructive-sql"],
  [mcp("mcp__db__executeSql", { sql: "truncate t" }), "mcp-destructive-sql"],
  [mcp("mcp__db__run_query", { q: { text: "DELETE FROM t" } }), "mcp-destructive-sql"],
  [mcp("mcp__db__execute_sql", { query: "SELECT * FROM users" }), null],
  [mcp("mcp__db__execute_sql", { query: "DELETE FROM t WHERE id = 1" }), null],
  [mcp("mcp__jira__add_comment", { body: "we should DROP TABLE x" }), null],
  // file tools are not MCP
  [mcp("Read", { file_path: "/x" }), null],
  // everyday commands
  [bash("ls -la"), null],
  [bash("pnpm test"), null],
  [bash("npm run build"), null],
  [bash("cat README.md | grep rm"), null],
  [bash("echo rm -rf /"), null],
]

for (const [input, expected] of cases) {
  const label = input.tool_input.command ?? `${input.tool_name} ${JSON.stringify(input.tool_input)}`
  test(`destructive: ${label} -> ${expected}`, () => {
    assert.equal(idOf(input), expected)
  })
}

test("every destructive rule has at least one asking case", () => {
  const pack = JSON.parse(readFileSync(packPath("destructive"), "utf8"))
  const hit = new Set(cases.map(([, id]) => id))
  for (const r of pack.rules) assert.ok(hit.has(r.id), r.id)
})

test("destructive rules do not make the script scan ask", async () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "gate-destr-")))
  mkdirSync(join(root, ".git"))
  writeFileSync(join(root, "build.sh"), "rm -rf dist\ngit push\n")
  const r = await gate(
    { tool_name: "Bash", tool_input: { command: "bash build.sh" }, cwd: root },
    rules,
    { env: {} },
  )
  assert.equal(r, null)
  // a script outside the project does not ask when nothing is scanned for
  const r2 = await gate(
    { tool_name: "Bash", tool_input: { command: "bash /usr/local/bin/x.sh" }, cwd: root },
    rules,
    { env: {} },
  )
  assert.equal(r2, null)
})

// ---------------------------------------------------------------------------
// New rule capabilities, with inline rules
// ---------------------------------------------------------------------------

const one = (rule) => parseRules({ rules: [rule] })

test("whenFlags: every group needs one flag; bundles only with shortBundles", () => {
  const base = { id: "t", kind: "cli-gated", programs: ["t"], gatedPrefixes: [[]], whenFlags: [["-a"], ["-b"]] }
  const strict = one(base)
  const bundled = one({ ...base, shortBundles: true })
  const id = (r, c) => classify(bash(c), r)?.reason.split(":")[0] ?? null
  assert.equal(id(strict, "t -a -b"), "t")
  assert.equal(id(strict, "t -ab"), null)
  assert.equal(id(bundled, "t -ab"), "t")
  assert.equal(id(bundled, "t -a"), null)
  assert.equal(id(bundled, "t -- -ab"), null)
})

test("unlessFlags keep exact matching without shortBundles", () => {
  const r = one({ id: "t", kind: "cli-gated", programs: ["t"], gatedPrefixes: [[]], unlessFlags: ["-f"] })
  assert.equal(classify(bash("t -dfoo"), r)?.reason, "t: gated invocation")
  assert.equal(classify(bash("t -f x"), r), null)
})

test("dynamicArgs: ask (default) vs ignore", () => {
  const rule = { id: "t", kind: "cli-gated", programs: ["t"], gatedPrefixes: [["x"]] }
  assert.equal(classify(bash("t $A"), one(rule))?.reason, "t: dynamic argument")
  assert.equal(classify(bash("t $A"), one({ ...rule, dynamicArgs: "ignore" })), null)
  assert.equal(classify(bash("t x $A"), one({ ...rule, dynamicArgs: "ignore" }))?.reason, "t: gated invocation")
})

test("whenArgs honours ignoreCase and matchStdin", () => {
  const rule = { id: "t", kind: "cli-gated", programs: ["t"], gatedPrefixes: [[]], whenArgs: ["^BAD$"] }
  assert.equal(classify(bash("t bad"), one(rule)), null)
  assert.ok(classify(bash("t bad"), one({ ...rule, ignoreCase: true })))
  assert.equal(classify(bash("t <<E\nBAD\nE"), one(rule)), null)
  assert.ok(classify(bash("t <<E\nBAD\nE"), one({ ...rule, whenArgs: ["BAD"], matchStdin: true })))
})

test("new rule fields are validated", () => {
  const base = { id: "t", kind: "cli-gated", programs: ["t"], gatedPrefixes: [[]] }
  for (const bad of [
    { whenFlags: [[]] },
    { whenFlags: ["-a"] },
    { whenArgs: ["("] },
    { shortBundles: "yes" },
    { dynamicArgs: "maybe" },
    { scriptScan: 1 },
  ]) {
    assert.throws(() => one({ ...base, ...bad }), RulesError, JSON.stringify(bad))
  }
  assert.throws(() => one({ id: "m", kind: "mcp-pattern" }), RulesError)
  assert.throws(() => one({ id: "m", kind: "mcp-pattern", inputPattern: "(" }), RulesError)
  assert.throws(() => one({ id: "m", kind: "mcp-pattern", toolWords: [""] }), RulesError)
})

test("mcp-pattern: tool regex alone, words split on camelCase", () => {
  const r = one({ id: "m", kind: "mcp-pattern", tool: "^mcp__danger__" })
  assert.equal(classify(mcp("mcp__danger__anything"), r)?.reason, "m: anything")
  assert.equal(classify(mcp("mcp__safe__anything"), r), null)
  const w = one({ id: "w", kind: "mcp-pattern", toolWords: ["purge"] })
  assert.ok(classify(mcp("mcp__x__purgeCache"), w))
  assert.equal(classify(mcp("mcp__x__purgecache"), w), null)
})
