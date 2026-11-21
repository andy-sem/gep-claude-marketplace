"""Gate.gate(): rule result, script scan fallback, optional Jev layer (in-process)."""

import pytest

from destructive_guard.gate.gate import Gate
from destructive_guard.rules.rule_loader import RuleLoader
from destructive_guard.scripts.script_collector import ScriptCollector
from testkit import DG
from testkit.projects import provision_project, temp_project

RULES = RuleLoader.load_rules(DG / "tests" / "fixtures" / "rules.json")


def bash(command, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def test_rule_result_skips_the_scan(tmp_path):
    def boom(*a, **k):
        raise AssertionError("scan must not run")

    trace = {}
    r = Gate(RULES, {}, collect_scripts=boom).gate(bash("terraform apply", tmp_path), trace=trace)
    assert r and r["decision"] == "ask"
    assert trace["rule"] == r


@pytest.mark.parametrize(
    "input",
    [{"tool_name": "Bash", "tool_input": {}}, {"tool_input": {"command": "ls"}}, []],
)
def test_closed_results_skip_the_scan(input):
    def boom(*a, **k):
        raise AssertionError("scan must not run")

    r = Gate(RULES, {"GATE_JEV": "1"}, collect_scripts=boom).gate(input)
    assert r["reason"].startswith("unparsable:")


def test_bash_without_rule_result_scans_scripts(tmp_path):
    root = provision_project(tmp_path)
    trace = {}
    r = Gate(RULES, {}).gate(bash("node scripts/provision-cloud-app-dev.mjs", root), trace=trace)
    assert r and r["reason"].startswith("script:")
    assert trace["rule"] == r
    assert Gate(RULES, {}).gate(bash("ls", root)) is None


def test_gate_jev_collects_scripts_even_with_a_rule_result(tmp_path):
    root = temp_project(tmp_path, {"go.sh": "echo hi\n"})
    seen = []

    def spy(command, where, project_root):
        seen.append(command)
        return ScriptCollector(RULES, where, project_root).collect(command)

    Gate(RULES, {}, collect_scripts=spy).gate(bash("terraform apply", root))
    assert seen == []
    # Jev on (invalid config here, so it asks gate-config), but the scan ran first.
    r = Gate(RULES, {"GATE_JEV": "1"}, collect_scripts=spy).gate(bash("terraform apply", root))
    assert seen == ["terraform apply"]
    assert r["reason"].startswith("gate-config:")
    assert "TYPESAFE_API_KEY" in r["reason"]


def test_scan_exception_asks_gate_config(tmp_path):
    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    r = Gate(RULES, {}, collect_scripts=boom).gate(bash("ls", tmp_path))
    assert r == {"decision": "ask", "reason": "gate-config: script scan failed: disk on fire"}


def test_jev_scope_leaves_the_rule_result(tmp_path):
    env = {"GATE_JEV": "1", "TYPESAFE_API_KEY": "k", "GATE_JEV_SCOPE": "mcp", "GATE_JEV_URL": "http://127.0.0.1:1/v1"}
    r = Gate(RULES, env).gate(bash("terraform apply", tmp_path))
    assert r["reason"].startswith("terraform:")
