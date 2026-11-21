"""gate(): rule result, script scan fallback, optional Jev layer (in-process)."""

import pytest

from destructive_guard import gate_scripts
from destructive_guard.gate_engine import gate
from destructive_guard.rules import load_rules
from testkit import DG
from testkit.projects import provision_project, temp_project

RULES = load_rules(DG / "tests" / "fixtures" / "rules.json")


def bash(command, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def test_rule_result_skips_the_scan(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("scan must not run")

    monkeypatch.setattr(gate_scripts, "collect_scripts", boom)
    trace = {}
    r = gate(bash("terraform apply", tmp_path), RULES, env={}, trace=trace)
    assert r and r["decision"] == "ask"
    assert trace["rule"] == r


@pytest.mark.parametrize(
    "input",
    [{"tool_name": "Bash", "tool_input": {}}, {"tool_input": {"command": "ls"}}, []],
)
def test_closed_results_skip_the_scan(monkeypatch, input):
    def boom(*a, **k):
        raise AssertionError("scan must not run")

    monkeypatch.setattr(gate_scripts, "collect_scripts", boom)
    r = gate(input, RULES, env={"GATE_JEV": "1"})
    assert r["reason"].startswith("unparsable:")


def test_bash_without_rule_result_scans_scripts(tmp_path):
    root = provision_project(tmp_path)
    trace = {}
    r = gate(bash("node scripts/provision-cloud-app-dev.mjs", root), RULES, env={}, trace=trace)
    assert r and r["reason"].startswith("script:")
    assert trace["rule"] == r
    assert gate(bash("ls", root), RULES, env={}) is None


def test_gate_jev_collects_scripts_even_with_a_rule_result(tmp_path, monkeypatch):
    root = temp_project(tmp_path, {"go.sh": "echo hi\n"})
    seen = []
    real = gate_scripts.collect_scripts

    def spy(*a, **k):
        seen.append(a[0])
        return real(*a, **k)

    monkeypatch.setattr(gate_scripts, "collect_scripts", spy)
    gate(bash("terraform apply", root), RULES, env={})
    assert seen == []
    # Jev on (invalid config here, so it asks gate-config), but the scan ran first.
    r = gate(bash("terraform apply", root), RULES, env={"GATE_JEV": "1"})
    assert seen == ["terraform apply"]
    assert r["reason"].startswith("gate-config:")
    assert "TYPESAFE_API_KEY" in r["reason"]


def test_scan_exception_asks_gate_config(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(gate_scripts, "collect_scripts", boom)
    r = gate(bash("ls", tmp_path), RULES, env={})
    assert r == {"decision": "ask", "reason": "gate-config: script scan failed: disk on fire"}


def test_jev_scope_leaves_the_rule_result(tmp_path):
    env = {"GATE_JEV": "1", "TYPESAFE_API_KEY": "k", "GATE_JEV_SCOPE": "mcp", "GATE_JEV_URL": "http://127.0.0.1:1/v1"}
    r = gate(bash("terraform apply", tmp_path), RULES, env=env)
    assert r["reason"].startswith("terraform:")
