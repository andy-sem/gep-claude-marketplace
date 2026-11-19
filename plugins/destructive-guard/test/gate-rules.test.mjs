import { test } from "node:test"
import assert from "node:assert/strict"
import { fileURLToPath } from "node:url"
import { classify, loadRules } from "../lib/gate-engine.mjs"

const rulesPath = fileURLToPath(new URL("./fixtures/rules.json", import.meta.url))
const rules = loadRules(rulesPath)

const bash = (command) => ({
  input: { tool_name: "Bash", tool_input: { command } },
  currentBranch: "PROJ-1/x",
})
const mcp = (tool_name, tool_input = {}) => ({
  input: { tool_name, tool_input },
  currentBranch: "PROJ-1/x",
})

const idOf = ({ input, currentBranch }) =>
  classify(input, rules, { currentBranch })?.reason.split(":")[0] ?? null

test("loadRules accepts the shipped rule file", () => {
  assert.ok(rules.rules.length > 0)
})

const cases = [
  // cloudctl
  [bash("cloudctl storage buckets create blob://x --dry-run"), "cloudctl"],
  [bash("cloudctl run services list --project p"), null],
  [bash("cloudctl info"), null],
  [bash("cloudctl version"), null],
  [bash("cloudctl config list"), null],
  [bash("cloudctl config get project"), null],
  [bash("cloudctl auth list"), null],
  [bash("cloudctl logs read --limit 5"), null],
  [bash("cloudctl run services describe svc"), null],
  [bash("cloudctl projects get-iam-policy p"), null],
  [bash("cloudctl run deploy svc --image i"), "cloudctl"],
  [bash("cloudctl projects add-iam-policy-binding p"), "cloudctl"],
  [bash("cloudctl auth login"), "cloudctl"],
  [bash("cloudctl frobnicate"), "cloudctl"],
  // dwh
  [bash("dwh ls"), null],
  [bash("dwh show ds.t"), null],
  [bash("dwh query 'select 1'"), "dwh"],
  [bash("dwh rm -f ds.t"), "dwh"],
  // blobctl
  [bash("blobctl ls blob://b"), null],
  [bash("blobctl cat blob://b/f"), null],
  [bash("blobctl stat blob://b/f"), null],
  [bash("blobctl cp f blob://b/f"), "blobctl"],
  [bash("blobctl rm blob://b/f"), "blobctl"],
  // psql / pg_restore / pg_dump
  [bash('psql -c "select 1"'), "psql"],
  [bash("psql"), "psql"],
  [bash("pg_restore -d app dump"), "pg_restore"],
  [bash("pg_restore -f out.sql dump"), null],
  [bash("pg_restore --file=out.sql dump"), null],
  [bash("pg_dump -h h app > f"), null],
  // dbhost cli
  [bash("npx dbhost db push"), "dbhost-cli"],
  [bash("dbhost db reset"), "dbhost-cli"],
  [bash("dbhost migration up"), "dbhost-cli"],
  [bash("dbhost migration repair 1"), "dbhost-cli"],
  [bash("dbhost migration list"), null],
  [bash("dbhost status"), null],
  // dbhost mcp
  [mcp("mcp__plugin_dbhost_dbhost__execute_sql"), "dbhost-mcp"],
  [mcp("mcp__plugin_dbhost_dbhost__apply_migration"), "dbhost-mcp"],
  [mcp("mcp__plugin_dbhost_dbhost__list_tables"), null],
  [mcp("mcp__plugin_dbhost_dbhost__get_project"), null],
  [mcp("mcp__plugin_dbhost_dbhost__search_docs"), null],
  [mcp("mcp__plugin_dbhost_dbhost__generate_typescript_types"), null],
  [mcp("mcp__plugin_dbhost_dbhost__query_logs"), null],
  [mcp("mcp__dbhost__some_future_tool"), "dbhost-mcp"],
  // cloudctl mcp
  [
    mcp("mcp__cloudctl__run_cloudctl_command", {
      args: ["run", "services", "list"],
    }),
    null,
  ],
  [
    mcp("mcp__cloudctl__run_cloudctl_command", {
      args: ["run", "deploy", "svc"],
    }),
    "cloudctl",
  ],
  [
    mcp("mcp__cloudctl__run_cloudctl_command", {
      args: ["cloudctl", "run", "services", "delete", "s"],
    }),
    "cloudctl",
  ],
  [mcp("mcp__cloudctl__run_cloudctl_command", {}), "unparsable"],
  // flag values before gated subcommands, runners
  [bash("dbhost --workdir apps/web db push"), "dbhost-cli"],
  [bash("dbhost db --db-url x push"), "dbhost-cli"],
  [bash("dbhost --workdir x db reset"), "dbhost-cli"],
  [bash("dbhost --workdir=infra db push"), "dbhost-cli"],
  [bash("cloudctl --project=p run deploy s"), "cloudctl"],
  [bash("pnpm dbhost db push"), "dbhost-cli"],
  [bash("pnpm -C apps/web exec dbhost db push"), "dbhost-cli"],
  [
    bash("pnpm --filter @acme/web exec dbhost db push"),
    "dbhost-cli",
  ],
  [bash("pnpm -F web dbhost db push"), "dbhost-cli"],
  [bash("pnpm cloudctl run deploy s"), "cloudctl"],
  [bash("pnpm dwh rm -f ds.t"), "dwh"],
  [bash("pnpm dlx dbhost@latest db push"), "dbhost-cli"],
  [bash("npm exec dbhost db push"), "dbhost-cli"],
  [bash("npm exec -- dbhost db push"), "dbhost-cli"],
  [bash("npx -c 'dbhost db push'"), "dbhost-cli"],
  [bash("yarn dbhost db push"), "dbhost-cli"],
  [bash("bunx dbhost db push"), "dbhost-cli"],
  [bash("dbhost db diff"), null],
  [bash("dbhost db diff -f x"), null],
  [bash("dbhost start"), null],
  [bash("pnpm dev:web"), null],
  [bash("pnpm --filter @acme/web test"), null],
  [bash("pnpm exec turbo lint --output-logs=errors-only"), null],
  // anchored reads, flag values are not verbs
  [bash("cloudctl sql users set-password u --password list"), "cloudctl"],
  [bash("cloudctl compute ssh vm --command reboot --zone list"), "cloudctl"],
  [bash("cloudctl compute ssh vm run services list"), "cloudctl"],
  [bash("cloudctl compute ssh list --command=reboot"), "cloudctl"],
  [bash("cloudctl run services delete list"), "cloudctl"],
  [bash("cloudctl run services list delete"), null],
  [bash("cloudctl --project p run services list"), null],
  [bash("cloudctl alpha run services list"), null],
  [bash("cloudctl beta run jobs describe j"), null],
  [bash("cloudctl run revisions list --service s"), null],
  [bash("cloudctl run revisions describe r"), null],
  [bash("cloudctl run jobs list"), null],
  [bash("cloudctl run jobs describe j"), null],
  [bash("cloudctl run jobs execute j"), "cloudctl"],
  [bash("cloudctl run revisions delete r"), "cloudctl"],
  [bash("cloudctl projects list --filter=x"), null],
  [bash("cloudctl config get-value project"), null],
  [bash("dwh --dataset_id ls query 'select 1'"), "dwh"],
  [bash("dwh --format=json ls"), null],
  [bash("blobctl -o ls rm blob://b"), "blobctl"],
  [bash("blobctl -m cp a blob://b"), "blobctl"],
  [
    mcp("mcp__cloudctl__run_cloudctl_command", {
      args: ["compute", "ssh", "vm", "run", "services", "list"],
    }),
    "cloudctl",
  ],
  [
    mcp("mcp__cloudctl__run_cloudctl_command", {
      args: ["sql", "users", "set-password", "u", "--password", "list"],
    }),
    "cloudctl",
  ],
  [
    mcp("mcp__cloudctl__run_cloudctl_command", {
      args: ["run", "revisions", "list"],
    }),
    null,
  ],
  // dynamic arguments
  [bash("dbhost db $ACTION"), "dbhost-cli"],
  [bash("dbhost db $(echo push)"), "dbhost-cli"],
  [bash("echo push | xargs dbhost db"), "dbhost-cli"],
  [
    bash("find . -name '*.sql' -execdir dbhost db push {} \\;"),
    "dbhost-cli",
  ],
  [bash("dbhost db $S/fill.py"), "dbhost-cli"],
  [bash("dbhost db $S/*.py"), "dbhost-cli"],
  [bash("dbhost db ${S:-x}/fill.py"), "dbhost-cli"],
  [bash("dbhost db $SCRIPT"), "dbhost-cli"],
  [bash("dbhost db $S/$F"), "dbhost-cli"],
  [bash("dbhost db $S/$(echo x).py"), "dbhost-cli"],
  [bash("echo $S | xargs dbhost db"), "dbhost-cli"],
  // a variable directory with a literal file name
  [bash("python3 $S/fill.py a b"), null],
  [bash("python3 ${S}/sub/fill.py"), null],
  [bash("ls $HOME"), null],
  // unknown wrappers and later programs
  [
    bash("apps/web/scripts/with-sops.sh secrets/e.env dbhost db push"),
    "dbhost-cli",
  ],
  [bash("apps/web/scripts/with-sops.sh secrets/e.env pnpm dev"), null],
  [bash("nice dbhost db push"), "dbhost-cli"],
  [bash("doas cloudctl run deploy s"), "cloudctl"],
  [bash("watch dbhost db push"), "dbhost-cli"],
  [bash("caffeinate dbhost db push"), "dbhost-cli"],
  [bash("builtin command dbhost db push"), "dbhost-cli"],
  [bash("coproc dbhost db push"), "dbhost-cli"],
  [bash("env -S 'cloudctl run deploy s'"), "cloudctl"],
  [bash("sudo -iu root dbhost db push"), "dbhost-cli"],
  [bash("script -q /dev/null dbhost db push"), "dbhost-cli"],
  [bash("find . -exec dbhost db push \\;"), "dbhost-cli"],
  [bash("uv run dbhost db push"), "dbhost-cli"],
  [bash("which psql"), null],
  [bash("rg -n psql docs"), null],
  [bash("man ls"), null],
  [bash("rg --pre-glob '*.gz' foo"), null],
  [bash("rg --pre psql x"), "inert program with command flag"],
  [bash("rg --pre=psql x"), "inert program with command flag"],
  [bash("man -P psql ls"), "inert program with command flag"],
  [bash("man --pager=psql ls"), "inert program with command flag"],
  [bash("less +'!psql' f"), "inert program with command flag"],
  [
    bash("find . -exec rg --pre psql x {} +"),
    "inert program with command flag",
  ],
  // MCP name variants
  [mcp("mcp__claude_ai_Dbhost__execute_sql"), "dbhost-mcp"],
  [mcp("mcp__claude_ai_Dbhost__list_tables"), null],
  [
    mcp("mcp__plugin_cloudctl_cloudctl__run_cloudctl_command", {
      args: ["run", "deploy", "s"],
    }),
    "cloudctl",
  ],
  [
    mcp("mcp__plugin_cloudctl_cloudctl__run_cloudctl_command", {
      args: ["run", "services", "list"],
    }),
    null,
  ],
  // more cloudctl / dbhost writes
  [bash("cloudctl app deploy app.yaml"), "cloudctl"],
  [bash("cloudctl secrets create s"), "cloudctl"],
  [bash("cloudctl run services update svc --image i"), "cloudctl"],
  [bash("cloudctl run services delete svc"), "cloudctl"],
  [bash("blobctl rb blob://b"), "blobctl"],
  [bash("dwh mk ds"), "dwh"],
  [bash("dwh cp a b"), "dwh"],
  [bash("psql -c 'delete from t'"), "psql"],
  [bash("dbhost migration up --linked"), "dbhost-cli"],
  [bash("dbhost migration list --linked"), null],
  [bash("dbhost functions deploy f"), "dbhost-cli"],
  [bash("dbhost secrets set A=1"), "dbhost-cli"],
  [bash("dbhost secrets unset A"), "dbhost-cli"],
  [bash("dbhost secrets list"), null],
  [bash("dbhost functions serve"), null],
  // terraform / tofu
  [
    bash("terraform -chdir=infra/cloud/environments/dev apply dev.tfplan"),
    "terraform",
  ],
  [bash("terraform apply"), "terraform"],
  [bash("terraform destroy"), "terraform"],
  [bash("tofu import a b"), "terraform"],
  [bash("terraform state rm x"), "terraform"],
  [bash("terraform state mv a b"), "terraform"],
  [bash("terraform force-unlock 1"), "terraform"],
  [bash("terraform test"), "terraform"],
  [bash("terraform taint a.b"), "terraform"],
  [bash("terraform untaint a.b"), "terraform"],
  [bash("terraform refresh"), "terraform"],
  [bash("terraform workspace delete x"), "terraform"],
  [bash("terraform plan"), null],
  [bash("terraform fmt"), null],
  [bash("terraform validate"), null],
  [bash("terraform -chdir=x init"), null],
  [bash("terraform state list"), null],
  [bash("terraform show"), null],
  [bash("terraform output"), null],
  [bash("terraform providers"), null],
  [bash("terraform version"), null],
  [bash("terraform graph"), null],
  [bash("tofu plan -out x"), null],
  // help flags and words
  [bash("cloudctl sql instances create --help"), null],
  [bash("cloudctl help run deploy"), null],
  [bash("cloudctl run deploy -h"), null],
  [bash("dwh mk --help"), null],
  [bash("blobctl rm --help"), null],
  [bash("dbhost db push --help"), null],
  [bash("dbhost db push -h"), null],
  [bash("terraform apply -help"), null],
  [bash("terraform apply -h"), null],
  [bash("psql --help"), null],
  [bash("pg_restore --help"), null],
  [
    mcp("mcp__cloudctl__run_cloudctl_command", {
      args: ["sql", "instances", "create", "--help"],
    }),
    null,
  ],
  [bash("cloudctl run deploy svc -- --help"), "cloudctl"],
  [bash("cloudctl run deploy --no-traffic --help"), "cloudctl"],
  [bash("psql -h db.example.com -c 'drop table t'"), "psql"],
  [bash('blobctl -h "Cache-Control:no-cache" cp f blob://b/f'), "blobctl"],
  [bash("psql help"), "psql"],
  [bash("blobctl help rm"), null],
  [bash("pg_restore -h host -d app dump"), "pg_restore"],
  // unrelated
  [bash("pnpm test"), null],
  [mcp("Read", { file_path: "/x" }), null],
]

test("wrangler, pulumi, cf-apply scripts and git push are not gated", () => {
  for (const command of [
    "wrangler deploy",
    "pulumi up",
    "python3 scripts/cf-apply-env.py",
    "git push --force origin main",
  ]) {
    assert.equal(idOf(bash(command)), null, command)
  }
})

for (const [c, expected] of cases) {
  const label =
    c.input.tool_input.command ??
    `${c.input.tool_name} ${JSON.stringify(c.input.tool_input)}`
  test(`${label} -> ${expected}`, () => {
    assert.equal(idOf(c), expected)
  })
}
