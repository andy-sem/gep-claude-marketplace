"""Script collection and scanning (port of gate-scripts.test.mjs), in-process on destructive_guard.gate_scripts."""

import json
from pathlib import Path

import pytest

from destructive_guard.errors import RulesError
from destructive_guard.gate_scripts import (
    collect_scripts,
    find_project_root,
    glob_to_regexp,
    scan_scripts,
)
from destructive_guard.rules.rule_loader import RuleLoader
from testkit import DG
from testkit.projects import provision_project, temp_project

SHIPPED = DG / "tests" / "fixtures" / "rules.json"
RULES = RuleLoader.load_rules(SHIPPED)


def collect_many(root: Path, commands: list[str], cwd: Path | None = None) -> list[dict]:
    return [collect_scripts(c, RULES, cwd=str(cwd or root), root=str(root)) for c in commands]


def collect(root: Path, command: str) -> dict:
    return collect_many(root, [command])[0]


def paths(c: dict) -> list[str]:
    return [f["path"] for f in c["files"]]


def scan_many(root: Path, commands: list[str]) -> list[str | None]:
    results = [scan_scripts(c, RULES) for c in collect_many(root, commands)]
    return [r["reason"] if r else None for r in results]


def test_find_project_root_git_ancestor_env_and_cwd_fallback(tmp_path, tmp_path_factory):
    root = temp_project(tmp_path, {"a/b/c.txt": "x"})
    bare = tmp_path_factory.mktemp("gate-noroot-").resolve()
    found = find_project_root(str(root / "a/b"))
    env_fallback = find_project_root(str(bare), {"CLAUDE_PROJECT_DIR": str(root)})
    cwd_fallback = find_project_root(str(bare), {})
    assert found == str(root)
    assert env_fallback == str(root), "env fallback"
    assert cwd_fallback == str(bare), "cwd fallback"


def test_shell_scripts_found_for_every_way_of_running_them(tmp_path):
    root = temp_project(tmp_path, {"x.sh": "echo hi\n", "infra/cloud/apply.sh": "echo apply\n"})
    commands = [
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
        f"bash {root / 'x.sh'}",
    ]
    extra = [
        "infra/cloud/apply.sh --apply",
        "cd infra/cloud && ./apply.sh",
        "(cd infra/cloud; bash apply.sh)",
    ]
    results = collect_many(root, commands + extra)
    for command, c in zip(commands, results[: len(commands)], strict=True):
        assert paths(c) == ["x.sh"], command
    for command, c in zip(extra, results[len(commands) :], strict=True):
        assert paths(c) == ["infra/cloud/apply.sh"], command


def test_bash_c_strings_and_stdin_shells_give_no_file(tmp_path):
    root = temp_project(tmp_path, {"x.sh": "echo hi\n"})
    plain, nested = collect_many(root, ["bash -c 'echo x'", "bash -c './x.sh'"])
    assert paths(plain) == []
    assert paths(nested) == ["x.sh"]


def test_cd_in_subshell_or_substitution_does_not_move_later_commands_popd_goes_back(tmp_path):
    root = temp_project(
        tmp_path,
        {"infra/ok.sh": "echo ok\n", "infra/apply.sh": "terraform apply\n", "apply.sh": "echo top\n"},
    )
    includes = [
        "(cd infra && bash ok.sh); bash infra/apply.sh",
        "pushd infra && bash ok.sh; popd; bash infra/apply.sh",
        "pushd infra > /dev/null; popd > /dev/null; bash infra/apply.sh",
        "echo $(cd infra); bash infra/apply.sh",
    ]
    exact = [
        # the group leaves the directory unchanged: `apply.sh` is the top-level file
        ("(cd infra); bash apply.sh", ["apply.sh"]),
        ("(cd infra) && cd infra && bash apply.sh", ["infra/apply.sh"]),
        # separate groups do not share a directory
        ("(cd infra); (cd infra; bash ok.sh)", ["infra/ok.sh"]),
        # inside the group the cd still applies, and nested cds stack
        ("(cd infra && (cd .. ; bash apply.sh))", ["apply.sh"]),
    ]
    results = collect_many(root, includes + [c for c, _ in exact])
    for command, c in zip(includes, results[: len(includes)], strict=True):
        assert "infra/apply.sh" in paths(c), command
    for (command, expected), c in zip(exact, results[len(includes) :], strict=True):
        assert paths(c) == expected, command


def test_sourced_file_resolved_against_the_directory_the_script_ran_in(tmp_path):
    root = temp_project(
        tmp_path,
        {
            "infra/wrap.sh": "source ./inner.sh\n",
            "infra/inner.sh": "terraform apply\n",
            "infra/cloud/apply.sh": ". ./common.sh\n",
            "infra/cloud/common.sh": "terraform apply\n",
            "pkg/package.json": json.dumps({"scripts": {"go": "bash go.sh"}}),
            "pkg/go.sh": "source ./helper.sh\n",
            "pkg/helper.sh": "terraform apply\n",
        },
    )
    cases = [
        ("cd infra && bash wrap.sh", "infra/inner.sh"),
        ("pushd infra && bash wrap.sh; popd", "infra/inner.sh"),
        ("(cd infra && bash wrap.sh)", "infra/inner.sh"),
        ("cd infra/cloud && ./apply.sh", "infra/cloud/common.sh"),
        ("pnpm -C pkg run go", "pkg/helper.sh"),
    ]
    results = collect_many(root, [c for c, _ in cases])
    for (command, inner), c in zip(cases, results, strict=True):
        assert inner in paths(c), command


def test_cd_after_shell_string_does_not_move_commands_inside_it(tmp_path):
    root = temp_project(
        tmp_path,
        {"infra/apply.sh": "terraform apply\n", "apply.sh": "echo top\n", "lib/x.txt": ""},
    )
    commands = [
        "cd infra && sh -c './apply.sh' && cd ..",
        "cd infra && sh -c './apply.sh' && cd -",
        "cd infra && bash -c 'bash apply.sh'; cd ../lib",
    ]
    *results, later_cd, inner_cd = collect_many(
        root,
        commands
        + [
            "bash -c 'bash infra/apply.sh'; cd lib",
            # a cd inside the string still applies inside it only
            "sh -c 'cd infra && bash apply.sh'; bash apply.sh",
        ],
    )
    for command, c in zip(commands, results, strict=True):
        assert paths(c) == ["infra/apply.sh"], command
    assert "infra/apply.sh" in paths(later_cd)
    assert paths(inner_cd) == ["apply.sh", "infra/apply.sh"]


def test_shell_strings_through_wrappers_and_runners_are_followed(tmp_path):
    root = temp_project(tmp_path, {"infra/apply.sh": "terraform apply\n", "x.sh": "echo hi\n"})
    commands = [
        "watch bash infra/apply.sh",
        "watch -n 5 'bash infra/apply.sh'",
        "npx -c 'bash infra/apply.sh'",
        "npx --call 'bash infra/apply.sh'",
        "pnpm exec sh -c 'bash infra/apply.sh'",
        "timeout 5 bash -c 'bash infra/apply.sh'",
        "sudo -E sh -c 'cd infra && bash apply.sh'",
        "cd infra && watch bash apply.sh",
    ]
    *results, unresolvable, twice = collect_many(
        root,
        commands
        + [
            # a string with an unresolvable expansion collects nothing
            'watch "bash $X"',
            # the same file reached twice is collected once
            "bash -c 'bash x.sh'; bash x.sh",
        ],
    )
    for command, c in zip(commands, results, strict=True):
        assert paths(c) == ["infra/apply.sh"], command
    assert paths(unresolvable) == []
    assert paths(twice) == ["x.sh"]


def test_node_targets_files_preloads_test_and_run(tmp_path):
    root = temp_project(
        tmp_path,
        {
            "a.mjs": "",
            "b.mjs": "",
            "pre.cjs": "",
            "t.test.mjs": "",
            "package.json": json.dumps({"scripts": {"go": "echo go"}}),
        },
    )
    cases = [
        ("node a.mjs", ["a.mjs"]),
        ("node --max-old-space-size=4096 a.mjs", ["a.mjs"]),
        ("node -C dev a.mjs b.mjs", ["a.mjs"]),
        ("node -r ./pre.cjs a.mjs", ["pre.cjs", "a.mjs"]),
        ("node --import ./pre.cjs a.mjs", ["pre.cjs", "a.mjs"]),
        ("node -e 'console.log(1)'", []),
        ("node -p 1", []),
        ("node --eval 1", []),
        ("node --test a.mjs b.mjs", ["a.mjs", "b.mjs"]),
        ('node --test ".claude/hooks/*.test.mjs"', []),
        ("node --run go", ["package.json#scripts.go"]),
    ]
    results = collect_many(root, [c for c, _ in cases])
    for (command, expected), c in zip(cases, results, strict=True):
        assert paths(c) == expected, command


def test_python_tsx_and_deno_targets(tmp_path):
    root = temp_project(tmp_path, {"a.py": "", "b.ts": "", "c.ts": ""})
    cases = [
        ("python a.py", ["a.py"]),
        ("python3 -u a.py", ["a.py"]),
        ("python3.12 -W ignore a.py", ["a.py"]),
        ("python3 -m http.server", []),
        ("python3 -c 'print(1)'", []),
        ("tsx b.ts", ["b.ts"]),
        ("tsx watch b.ts", ["b.ts"]),
        ("pnpm exec tsx b.ts", ["b.ts"]),
        ("npx tsx c.ts", ["c.ts"]),
        ("deno run --allow-read b.ts", ["b.ts"]),
        ("deno test", []),
    ]
    results = collect_many(root, [c for c, _ in cases])
    for (command, expected), c in zip(cases, results, strict=True):
        assert paths(c) == expected, command


def test_package_scripts_resolve_from_cwd_or_dir_options(tmp_path):
    root = temp_project(
        tmp_path,
        {
            "package.json": json.dumps({"scripts": {"build": "turbo build", "db:x": "node scripts/a.mjs"}}),
            "apps/web/package.json": json.dumps({"scripts": {"dev": "vite dev"}}),
            "scripts/a.mjs": "console.log(1)\n",
        },
    )
    build = ["package.json#scripts.build"]
    dev = ["apps/web/package.json#scripts.dev"]
    cases = [
        ("pnpm run build", build),
        ("npm run-script build", build),
        ("yarn run build", build),
        ("bun run build", build),
        ("pnpm build", build),
        ("yarn build", build),
        ("npm build", []),
        ("pnpm install", []),
        ("pnpm -C apps/web dev", dev),
        ("pnpm --dir apps/web run dev", dev),
        ("npm --prefix apps/web run dev", dev),
        ("yarn --cwd apps/web run dev", dev),
        ("pnpm missing", []),
        # the commands in a script body are followed
        ("pnpm db:x", ["package.json#scripts.db:x", "scripts/a.mjs"]),
    ]
    results = collect_many(root, [c for c, _ in cases])
    for (command, expected), c in zip(cases, results, strict=True):
        assert paths(c) == expected, command
    other = temp_project(tmp_path, {"package.json": json.dumps({"scripts": {"test": "node --test"}})})
    assert paths(collect(other, "npm test")) == ["package.json#scripts.test"]


def test_gh_workflow_run_resolves_file_name_or_workflow_name(tmp_path):
    root = temp_project(
        tmp_path,
        {
            ".github/workflows/deploy.yml": "name: Deploy Cloud\non: workflow_dispatch\n",
            ".github/workflows/other.yaml": "name: Other\n",
        },
    )
    deploy = [".github/workflows/deploy.yml"]
    cases = [
        ("gh workflow run deploy.yml", deploy),
        ("gh workflow run deploy.yml -f env=dev --ref main", deploy),
        ("gh workflow run -r main other.yaml", [".github/workflows/other.yaml"]),
        ('gh workflow run "Deploy Cloud"', deploy),
        ("gh workflow run 12345", []),
        ("gh workflow run nothing.yml", []),
        ("gh workflow list", []),
    ]
    results = collect_many(root, [c for c, _ in cases])
    for (command, expected), c in zip(cases, results, strict=True):
        assert paths(c) == expected, command


def test_source_and_import_following_resolution_extensions_depth_cycles(tmp_path):
    root = temp_project(
        tmp_path,
        {
            "run.sh": (
                "#!/bin/bash\n"
                'source "$(dirname "$0")/lib/a.sh"\n'
                '. "${BASH_SOURCE%/*}/lib/b.sh"\n'
                "if true; then source lib/c.sh; fi\n"
                'source "$X/skip.sh"\n'
            ),
            "lib/a.sh": "echo a\n",
            "lib/b.sh": "echo b\n",
            "lib/c.sh": "echo c\n",
            "main.mjs": (
                'import { a } from "./m/a.mjs"\n'
                'import "./m/side.js"\n'
                'export * from "./m/ex"\n'
                'const x = await import("./m/dyn.ts")\n'
                'const y = require("./m/req.cjs")\n'
                'import fs from "node:fs"\n'
                'import z from "left-pad"\n'
                "import {\n"
                "  multi,\n"
                '} from "./m/multi.mjs"\n'
            ),
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
        },
    )
    run, main, one, two, idx, cyc = collect_many(
        root,
        [
            "bash run.sh",
            "node main.mjs",
            "node chain/one.mjs",
            "node chain/two.mjs",
            "node idx/main.mjs",
            "node cyc/a.mjs",
        ],
    )
    assert paths(run) == ["run.sh", "lib/a.sh", "lib/b.sh", "lib/c.sh"]
    assert paths(main) == [
        "main.mjs",
        "m/a.mjs",
        "m/side.js",
        "m/ex.ts",
        "m/dyn.ts",
        "m/req.cjs",
        "m/multi.mjs",
        "chain/one.mjs",
        "chain/two.mjs",
    ]
    assert [f["depth"] for f in main["files"]] == [0, 1, 1, 1, 1, 1, 1, 2, 3]
    # depth 3 is the last level that is read
    assert paths(one) == ["chain/one.mjs", "chain/two.mjs", "chain/three.mjs", "chain/four.mjs"]
    assert paths(two) == ["chain/two.mjs", "chain/three.mjs", "chain/four.mjs"]
    assert paths(idx) == ["idx/main.mjs", "idx/lib/index.mjs"]
    assert paths(cyc) == ["cyc/a.mjs", "cyc/b.mjs"]


def test_script_sourcing_script_dir_resolves_against_the_script(tmp_path):
    root = temp_project(
        tmp_path,
        {
            "tools/run.sh": 'source "$SCRIPT_DIR/helper.sh"\nsource ${SCRIPT_DIR}/two.sh\n',
            "tools/helper.sh": "",
            "tools/two.sh": "",
        },
    )
    assert paths(collect(root, "bash tools/run.sh")) == ["tools/run.sh", "tools/helper.sh", "tools/two.sh"]


def test_64_kb_per_file_cut_is_kept_and_reported_as_a_problem(tmp_path):
    root = temp_project(tmp_path, {"big.mjs": f"// {'x' * 70000}\ncloudctl\n"})
    c = collect(root, "node big.mjs")
    assert len(c["files"]) == 1
    assert c["files"][0]["truncated"] is True
    assert len(c["files"][0]["content"]) == 65536
    assert c["files"][0]["size"] > 65536
    assert c["problems"] == [{"path": "big.mjs", "reason": "exceeds 64 KB", "exempt": False}]
    assert scan_many(root, ["node big.mjs"]) == ["script: big.mjs exceeds 64 KB"]


def test_more_than_32_files_stops_following_and_is_a_problem(tmp_path):
    files = {f"m{i}.mjs": "" for i in range(1, 41)}
    files["m0.mjs"] = "".join(f'import "./m{i}.mjs"\n' for i in range(1, 41))
    root = temp_project(tmp_path, files)
    c = collect(root, "node m0.mjs")
    assert len(c["files"]) == 32
    assert [p["reason"] for p in c["problems"]] == ["more than 32 files"]


def test_files_outside_project_symlinks_out_and_non_regular_files_are_problems(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("gate-outside-").resolve()
    (outside / "x.sh").write_text("echo\n")
    root = temp_project(tmp_path, {"dir/keep": ""})
    (root / "link.sh").symlink_to(outside / "x.sh")
    out_x = str(outside / "x.sh")
    absolute, link, directory, command_word, system = collect_many(
        root,
        [
            f"bash {out_x}",
            "bash link.sh",
            "bash dir",
            # an absolute path outside the project that is a command word is a system program
            f"{out_x} --flag",
            "/usr/bin/env true",
        ],
    )

    def reasons(c):
        return [f"{p['path']} {p['reason']}" for p in c["problems"]]

    assert reasons(absolute) == [f"{out_x} is outside the project"]
    assert reasons(link) == ["link.sh is outside the project"]
    assert reasons(directory) == ["dir is not a regular file"]
    assert reasons(command_word) == []
    assert system["problems"] == []


def test_missing_glob_and_dynamic_paths_are_skipped(tmp_path):
    root = temp_project(tmp_path, {"a.sh": ""})
    commands = [
        "bash missing.sh",
        "bash a-*.sh",
        "bash $SCRIPT",
        "bash $(echo a).sh",
        'bash "${DIR}/a.sh"',
        "node ~/x.mjs",
        "cd $X && bash a.sh",
        "cd missing && bash a.sh",
    ]
    for command, c in zip(commands, collect_many(root, commands), strict=True):
        assert c["files"] == [], command
        assert c["problems"] == [], command


def test_unparsable_command_collects_nothing(tmp_path):
    root = temp_project(tmp_path, {"a.sh": ""})
    assert collect(root, 'bash "a.sh') == {"files": [], "problems": []}


def test_scan_scripts_program_names_patterns_and_reasons(tmp_path):
    root = temp_project(
        tmp_path,
        {
            "tf.sh": "terraform -chdir=infra apply\n",
            "tofu.sh": "# plain\ntofu import a b\n",
            "g.sh": "echo cloudctl-like\n/usr/bin/cloudctl run deploy\n",
            "ref.mjs": 'fetch("https://run.acmecloudapis.com/v2/x")\n',
            "sup.mjs": 'import { createClient } from "@dbhost/dbhost-js"\n',
            "pg.mjs": 'const u = "postgresql://u@h/db"\n',
            "gh.mjs": 'const a = "acmecloud-github-actions/auth"\n',
            "words.sh": "echo terraformer my-psql psqlx a.dwh\n",
            "cf.mjs": 'await $`wrangler deploy`\nfetch("https://api.cloudflare.com/x")\n',
            "ssr.mjs": 'import x from "@dbhost/ssr"\n',
        },
    )
    tf, tofu, g, ref, sup, pg, gh, words, cf, ssr = scan_many(
        root,
        [
            "bash tf.sh",
            "bash tofu.sh",
            "bash g.sh",
            "node ref.mjs",
            "node sup.mjs",
            "node pg.mjs",
            "node gh.mjs",
            "bash words.sh",
            "node cf.mjs",
            "node ssr.mjs",
        ],
    )
    assert tf == "script: tf.sh runs terraform"
    assert tofu == "script: tofu.sh runs tofu"
    assert g == "script: g.sh runs cloudctl"
    assert ref.startswith("script: ref.mjs references acmecloudapis")
    assert sup.startswith("script: sup.mjs references @dbhost")
    assert pg.startswith("script: pg.mjs references postgres")
    assert gh.startswith("script: gh.mjs references acmecloud-github")
    assert words is None
    assert cf is None
    assert ssr is None
    assert scan_scripts({"files": [], "problems": []}, RULES) is None
    assert scan_scripts(None, RULES) is None


def test_scan_scripts_workflow_with_acmecloud_actions_step_asks(tmp_path):
    root = temp_project(
        tmp_path,
        {
            ".github/workflows/deploy.yml": (
                "name: Deploy\n"
                "jobs:\n"
                "  d:\n"
                "    steps:\n"
                "      - uses: acmecloud-github-actions/auth@v2\n"
            ),
        },
    )
    (reason,) = scan_many(root, ["gh workflow run deploy.yml"])
    assert reason.startswith("script: .github/workflows/deploy.yml references")


def test_scan_scripts_package_script_body_running_gated_program_asks(tmp_path):
    root = temp_project(
        tmp_path,
        {"package.json": json.dumps({"scripts": {"push": "dbhost db push", "hi": "echo hi"}})},
    )
    assert scan_many(root, ["pnpm push", "pnpm hi"]) == ["script: package.json#scripts.push runs dbhost", None]


def test_exempt_test_files_and_their_imports_are_not_scanned(tmp_path):
    root = temp_project(
        tmp_path,
        {
            "scripts/a.test.mjs": 'import "./runner.mjs"\n',
            "scripts/runner.mjs": 'spawn("terraform", ["apply"])\n',
            "scripts/other.mjs": 'spawn("terraform", ["apply"])\n',
            "scripts/ticket-flow/deep/x.test.mjs": 'import "../../other.mjs"\n',
            ".claude/hooks/h.test.mjs": "terraform apply\n",
            "scripts/sub/c.test.mjs": "terraform apply\n",
        },
    )
    (a,) = collect_many(root, ["node scripts/a.test.mjs"])
    assert paths(a) == ["scripts/a.test.mjs", "scripts/runner.mjs"]
    assert a["files"][1]["exempt"] is True
    assert scan_many(
        root,
        [
            "node scripts/a.test.mjs",
            "node scripts/ticket-flow/deep/x.test.mjs",
            "node --test .claude/hooks/h.test.mjs",
            "node scripts/other.mjs",
            # `scripts/*.test.mjs` does not cover nested directories
            "node scripts/sub/c.test.mjs",
        ],
    ) == [
        None,
        None,
        None,
        "script: scripts/other.mjs runs terraform",
        "script: scripts/sub/c.test.mjs runs terraform",
    ]


def test_exempt_file_that_is_too_large_does_not_ask(tmp_path):
    root = temp_project(tmp_path, {"scripts/big.test.mjs": "x" * 70000})
    assert scan_many(root, ["node scripts/big.test.mjs"]) == [None]


def test_glob_to_regexp_supports_doublestar_slash_doublestar_star_and_question():
    cases = [
        ("a/**/b.js", "a/b.js", True),
        ("a/**/b.js", "a/x/y/b.js", True),
        ("a/*.js", "a/x/b.js", False),
        ("a/*.js", "a/b.js", True),
        ("a/?.js", "a/b.js", True),
        ("a/?.js", "a/bc.js", False),
        ("a/**", "a/x/y", True),
        ("a.b", "axb", False),
    ]
    for glob, text, expected in cases:
        assert bool(glob_to_regexp(glob).search(text)) is expected, (glob, text)


def test_load_rules_validates_script_patterns_and_script_scan_exempt(tmp_path):
    p = tmp_path / "r.json"
    for extra in [
        {"scriptPatterns": ["("]},
        {"scriptPatterns": [1]},
        {"scriptPatterns": "x"},
        {"scriptScanExempt": [1]},
        {"scriptScanExempt": [""]},
        {"scriptScanExempt": "x"},
    ]:
        p.write_text(json.dumps(extra))
        with pytest.raises(RulesError):
            RuleLoader.load_rules(p)
    ok_path = tmp_path / "ok.json"
    ok_path.write_text(json.dumps({"scriptPatterns": ["a+b"], "scriptScanExempt": ["x/*.js"]}))
    empty_path = tmp_path / "empty.json"
    empty_path.write_text(json.dumps({}))
    ok, empty, shipped = RuleLoader.load_rules(ok_path), RuleLoader.load_rules(empty_path), RuleLoader.load_rules(SHIPPED)
    assert ok["scriptPatterns"][0].search("aab")
    assert ok["scriptScanExempt"] == ["x/*.js"]
    assert empty["scriptPatterns"] == []
    assert empty["scriptScanExempt"] == []
    # the shipped file carries the spec values
    assert len(shipped["scriptPatterns"]) == 9
    assert shipped["scriptScanExempt"] == [
        ".claude/hooks/*.test.mjs",
        "scripts/*.test.mjs",
        "scripts/ticket-flow/**/*.test.mjs",
    ]


ENV = "infra/cloud/environments/preview-x"


def test_terraform_test_sends_root_and_test_dir_tftest_files_as_exempt_context(tmp_path):
    root = temp_project(
        tmp_path,
        {
            f"{ENV}/main.tf": 'provider "acmecloud" {}\n',
            f"{ENV}/root.tftest.hcl": "# runs cloudctl and terraform apply\nrun {}\n",
            f"{ENV}/tests/b.tftest.hcl": 'mock_provider "acmecloud" {}\n',
            f"{ENV}/tests/a.tftest.hcl": 'mock_provider "acmecloud" {}\n',
            f"{ENV}/tests/notes.md": "x\n",
            f"{ENV}/other/c.tftest.hcl": "run {}\n",
        },
    )
    expected = [f"{ENV}/root.tftest.hcl", f"{ENV}/tests/a.tftest.hcl", f"{ENV}/tests/b.tftest.hcl"]
    commands = [
        f"cd {ENV} && terraform test",
        f"terraform -chdir={ENV} test",
        f"tofu -chdir={ENV} test -verbose",
        f"docker run --rm -w {root / ENV} --entrypoint terraform hashicorp/terraform:1.17.0 test",
        f"D={root}; P=$D/{ENV}; docker run --rm --workdir=${{P}} --entrypoint terraform img test",
    ]
    *results, other = collect_many(root, commands + [f"terraform -chdir={ENV} test -test-directory=other"])
    for command, c in zip(commands, results, strict=True):
        assert paths(c) == expected, command
        assert all(f["exempt"] for f in c["files"]), f"{command}: context files are exempt"
    assert paths(other) == [f"{ENV}/root.tftest.hcl", f"{ENV}/other/c.tftest.hcl"]
    # a test file that names a gated program does not ask through the script scan
    assert scan_many(root, [f"cd {ENV} && terraform test"]) == [None]


def test_terraform_test_sends_nothing_when_directory_unknown_or_not_local(tmp_path):
    root = temp_project(tmp_path, {f"{ENV}/tests/a.tftest.hcl": "run {}\n"})
    commands = [
        f"cd {ENV} && terraform plan",
        f"cd {ENV} && terraform validate",
        "terraform -chdir=$X test",
        "cd $X && terraform test",
        "docker run --rm -w $X --entrypoint terraform img test",
        f"cd {ENV} && docker run --rm --entrypoint terraform img test",
        f"cd {ENV} && docker run --rm -w tests --entrypoint terraform img test",
        f"cd {ENV} && ssh host terraform test",
        f"(P={root / ENV}); docker run -w $P --entrypoint terraform img test",
    ]
    for command, c in zip(commands, collect_many(root, commands), strict=True):
        assert paths(c) == [], command


def test_variables_assigned_earlier_resolve_script_paths(tmp_path):
    root = temp_project(tmp_path, {"infra/apply.sh": "echo apply\n"})
    commands = [
        "S=infra/apply.sh; bash $S",
        "D=infra; S=${D}/apply.sh; bash $S",
        "D=infra\ncd $D && ./apply.sh",
    ]
    *results, prefix = collect_many(root, commands + ["S=infra/apply.sh true; bash $S"])
    for command, c in zip(commands, results, strict=True):
        assert paths(c) == ["infra/apply.sh"], command
    # a prefix assignment applies to its own command only
    assert paths(prefix) == []


def test_scan_matches_hook_rows_on_corpus_projects(tmp_path):
    """The script rows of test_gate_hook.py, through the Python scan."""
    terraform = temp_project(
        tmp_path, {"infra/cloud/apply.sh": "#!/bin/bash\nterraform -chdir=environments/dev apply dev.tfplan\n"}
    )
    cloudflare = temp_project(
        tmp_path,
        {"scripts/cf.mjs": 'await fetch("https://api.cloudflare.com/client/v4/x")\nspawn("wrangler", ["deploy"])\n'},
    )
    (tf,) = scan_many(terraform, ["bash infra/cloud/apply.sh --apply"])
    assert tf == "script: infra/cloud/apply.sh runs terraform"
    (provision,) = scan_many(provision_project(tmp_path), ["node scripts/provision-cloud-app-dev.mjs"])
    assert provision.startswith("script: scripts/provision-cloud-app-dev.mjs ")
    assert scan_many(cloudflare, ["node scripts/cf.mjs"]) == [None]
