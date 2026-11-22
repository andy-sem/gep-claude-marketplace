"""Contract: the check CLI (port of check.test.mjs)."""

import json
import re

import pytest

from testkit.check_cli import CheckRunner
from testkit.hook import HookRunner
from testkit.legacy_gate import LegacyGate
from testkit.projects import TempProject


def check_json(impl, *args, env=None, cwd=None):
    proc = CheckRunner.run_check(impl, "--json", *args, env=env or {}, cwd=cwd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def test_parse_args_command_mcp_config_and_options(impl, tmp_path):
    assert check_json(impl, "git push -f", cwd=tmp_path)["command"] == "git push -f"
    assert check_json(impl, "--", "rm", "-rf", "x", cwd=tmp_path)["command"] == "rm -rf x"
    m = check_json(impl, "--mcp", "mcp__db__q", '{"a":1}', cwd=tmp_path)
    assert m["tool"] == "mcp__db__q"
    assert m["input"] == {"a": 1}
    assert check_json(impl, "--mcp", "mcp__x__y", cwd=tmp_path)["input"] == {}
    assert "packs" in check_json(impl, cwd=tmp_path)
    assert "packs" in check_json(impl, "--config", cwd=tmp_path)
    o = check_json(impl, "--cwd", str(tmp_path), "ls", cwd=tmp_path)
    assert o["command"] == "ls"


@pytest.mark.parametrize(
    "argv",
    [["--nope"], ["--mcp"], ["--mcp", "Bash"], ["--mcp", "mcp__x__y", "{"], ["--mcp", "mcp__x__y", "[1]"], ["--cwd"], ["--"]],
    ids=json.dumps,
)
def test_usage_errors_exit_2(impl, argv):
    proc = CheckRunner.run_check(impl, *argv)
    assert proc.returncode == 2
    assert re.match(r"^usage error: ", proc.stdout)


@pytest.mark.parametrize(
    ("call", "decision", "source"),
    [
        ({"bash": "ls -la"}, "none", None),
        ({"bash": "git status"}, "none", None),
        ({"bash": "git push origin main"}, "none", None),
        ({"bash": "git push -f origin main"}, "ask", "git-push-force"),
        ({"bash": "rm -rf build"}, "ask", "rm-recursive-force"),
        ({"mcp": "mcp__db__drop_table", "input": {"table": "x"}}, "ask", "mcp-destructive-tool"),
        ({"mcp": "mcp__db__execute_sql", "input": {"query": "DROP TABLE x"}}, "ask", "mcp-destructive-sql"),
        ({"mcp": "mcp__db__execute_sql", "input": {"query": "SELECT 1"}}, "none", None),
    ],
    ids=json.dumps,
)
def test_check_call_default_packs(impl, tmp_path, call, decision, source):
    r = CheckRunner.check_call(impl, call, cwd=tmp_path)
    assert r["decision"] == decision
    assert r["source"] == source
    assert r["jev"] == "off"


def test_check_call_honours_disable_enabled_and_checks(impl, tmp_path):
    push = {"bash": "git push -f"}
    assert CheckRunner.check_call(impl, push, env={"GATE_DISABLE_RULES": "git-push-force"}, cwd=tmp_path)["decision"] == "none"
    off = CheckRunner.check_call(impl, push, env={"GATE_ENABLED": "0"}, cwd=tmp_path)
    assert off["decision"] == "none"
    assert "disabled" in off["reason"]
    tf = {"bash": "terraform apply"}
    assert CheckRunner.check_call(impl, tf, cwd=tmp_path)["decision"] == "none"
    assert CheckRunner.check_call(impl, tf, env={"GATE_CHECKS": "destructive,terraform"}, cwd=tmp_path)["decision"] == "ask"


@pytest.mark.parametrize(
    "env",
    [
        {"GATE_CHECKS": "nope"},
        {"GATE_STRICT": "maybe"},
        {"GATE_DISABLE_RULES": "no-such-rule"},
        {"GATE_CHECKS": "none", "GATE_RULES_FILE": "/nonexistent/rules.json"},
    ],
    ids=json.dumps,
)
def test_check_call_config_errors_ask_gate_config(impl, tmp_path, env):
    r = CheckRunner.check_call(impl, {"bash": "ls"}, env=env, cwd=tmp_path)
    assert r["decision"] == "ask"
    assert r["source"] == "gate-config"


def test_check_never_contacts_jev_until_l4(impl, tmp_path):
    # An unreachable URL: a request would only change the timing, never the answer.
    env = {"TYPESAFE_API_KEY": "k", "GATE_JEV_URL": "http://127.0.0.1:1/v1"}
    r = CheckRunner.check_call(impl, {"bash": "git push -f"}, env=env, cwd=tmp_path)
    assert r["source"] == "git-push-force"
    assert r["jev"] == "off"


def test_effective_config_defaults_ids_redaction_errors(impl, tmp_path):
    c = check_json(impl, "--config", cwd=tmp_path)
    assert c["packs"] == ["base", "destructive"]
    assert c["strict"] is False
    assert "git-push-force" in c["ruleIds"]
    assert c["jev"] == {"enabled": False}

    env = {"TYPESAFE_API_KEY": "sekret-123"}
    proc = CheckRunner.run_check(impl, "--json", "--config", env=env, cwd=tmp_path)
    j = json.loads(proc.stdout)
    assert j["jev"]["enabled"] is True
    assert j["jev"]["apiKey"] == "[set]"
    assert j["jev"]["prompt"] == "destructive"
    assert "sekret-123" not in proc.stdout

    assert re.match(r"^gate-config: ", check_json(impl, "--config", env={"GATE_CHECKS": "nope"}, cwd=tmp_path)["error"])
    assert check_json(impl, "--config", env={"GATE_JEV_TIMEOUT_MS": "x", "TYPESAFE_API_KEY": "k"}, cwd=tmp_path)["jev"]["error"].startswith("gate-config: GATE_JEV_TIMEOUT_MS")


def test_cli_text_and_json_output_key_never_printed(impl, tmp_path):
    env = {"TYPESAFE_API_KEY": "sekret-123"}
    text = CheckRunner.run_check(impl, "git push --force", env=env, cwd=tmp_path)
    assert text.returncode == 0
    assert re.search(r"decision: ask", text.stdout)
    assert re.search(r"source: +git-push-force", text.stdout)
    js = CheckRunner.run_check(impl, "--json", "--mcp", "mcp__db__drop_table", "{}", env=env, cwd=tmp_path)
    assert json.loads(js.stdout)["source"] == "mcp-destructive-tool"
    conf = CheckRunner.run_check(impl, env=env, cwd=tmp_path)
    assert re.search(r"packs: +base, destructive", conf.stdout)
    assert re.search(r"api key \[set\]", conf.stdout)
    for out in (text.stdout, js.stdout, conf.stdout):
        assert "sekret-123" not in out


@pytest.mark.parametrize(
    "args",
    [
        "'rm -rf build'",
        "'git push --force origin main'",
        """--json 'psql -c "DROP TABLE x"'""",
        """--mcp mcp__db__execute_sql '{"query":"DROP TABLE users"}'""",
        "--config",
    ],
)
def test_documented_invocations_pass_the_gate(impl, tmp_path, args):
    command = impl.check_invocation(args)
    assert LegacyGate.run(HookRunner.bash_input(command, tmp_path), cwd=tmp_path).stdout == ""


def test_cwd_resolves_scripts_the_command_runs(impl, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "x.sh").write_text("terraform apply\n")
    env = {"GATE_CHECKS": "destructive,terraform"}
    r = CheckRunner.check_call(impl, {"bash": "bash x.sh"}, env=env, cwd=work)
    assert r["source"] == "script"
    assert re.search(r"x\.sh runs terraform", r["reason"])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert CheckRunner.check_call(impl, {"bash": "bash x.sh"}, env=env, cwd=elsewhere)["decision"] == "none"


def test_relative_rules_file_resolves_against_git_root_of_cwd(impl, tmp_path):
    rules = {"rules": [{"id": "deployctl", "kind": "cli-gated", "programs": ["deployctl"], "gatedPrefixes": [["release"]]}]}
    root = TempProject.temp_project(tmp_path, {".claude/rules.json": json.dumps(rules), "src/.keep": ""})
    env = {"GATE_CHECKS": "none", "GATE_RULES_FILE": ".claude/rules.json"}
    r = CheckRunner.check_call(impl, {"bash": "deployctl release v1"}, env=env, cwd=root / "src")
    assert r["decision"] == "ask"
    assert r["source"] == "deployctl"
