"""Contract: hooks/gate.sh with the Jev-only hook against a local Jev mock."""

import json
import re

import pytest

from dg_testkit import DG, REPO
from dg_testkit.hook import HookRunner
from dg_testkit.jev_mock import JevMock

HERE = DG / "tests"
RISKY = JevMock.probs(0.1, 0.1, 0.6, 0.2)
SAFE = JevMock.probs(0.01, 0.97, 0.01, 0.01)
ASK_PREFIX = '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":'


@pytest.fixture
def run(jev):
    """Runs the hook against the mock; `answer` is a probabilities dict or {"kind": ..., "status": ...}."""

    def go(stdin, answer=SAFE, env=None, cwd=None):
        if "kind" in answer or "status" in answer:
            jev.answer(**answer)
        else:
            jev.answer(answer)
        key = {"TYPESAFE_API_KEY": "test-key", "GATE_JEV_URL": jev.url, "GATE_JEV_PROMPT": "cloud-change"}
        return HookRunner.run(stdin, key, env or {}, cwd=cwd)

    return go


def _fake_engine(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(f"#!/usr/bin/env bash\n{body}\n")
    p.chmod(0o755)
    return str(p)


def test_risky_call_asks_with_jev_reason(run):
    r = run(HookRunner.bash_input("terraform apply", HERE), RISKY)
    assert r.status == 0
    assert r.stdout == (
        ASK_PREFIX + '"jev: cloud_or_data_change p=0.60 risk=0.80"}}'
    )


def test_safe_call_gives_no_output(run):
    r = run(HookRunner.bash_input("git status", HERE), SAFE)
    assert (r.status, r.stdout) == (0, "")


def test_jev_down_asks_with_a_warning(run):
    r = run(HookRunner.bash_input("git status", HERE), {"status": 503})
    assert r.stdout == (
        ASK_PREFIX + '"jev-unavailable: http 503"},"systemMessage":"destructive-guard: Jev returned http 503; '
        'asking you instead. GATE_ENABLED=0 turns the gate off."}'
    )


def test_env_call_is_not_sent_and_warns(run, jev):
    r = run(HookRunner.bash_input("cat .env", HERE), RISKY)
    assert json.loads(r.stdout) == {
        "systemMessage": "destructive-guard: call mentions a .env file and was not sent to Jev; Claude Code's permissions apply"
    }
    assert jev.hits == 0


def test_no_key_is_silent_per_call():
    r = HookRunner.run(HookRunner.bash_input("rm -rf /", HERE))
    assert (r.status, r.stdout) == (0, "")


@pytest.mark.parametrize("stdin", ["not json", "", "null", '"x"', '{"tool_input": {}}', '{"tool_name": 3}'])
def test_unreadable_input_asks_even_without_a_key(stdin):
    r = HookRunner.run(stdin)
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "plugin-fault: bad hook input"
    assert "could not read the hook input" in out["systemMessage"]


@pytest.mark.parametrize("stdin", ['{"tool_name":"Read","tool_input":{"file_path":"/x"}}', '{"tool_name":"Bash","tool_input":{}}'])
def test_calls_that_need_no_decision_give_no_output(run, jev, stdin):
    assert run(stdin, RISKY).stdout == ""
    assert jev.hits == 0


def test_interpreter_unavailable_asks():
    r = HookRunner.run(HookRunner.bash_input("git status", HERE), {"GATE_INFRA_PYTHON": "/nonexistent"})
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "plugin-fault: no Python >= 3.14 found (set GATE_INFRA_PYTHON)"
    assert out["systemMessage"].startswith("destructive-guard: no Python >= 3.14 found")


def test_engine_partial_json_then_nonzero_gives_fixed_ask(tmp_path):
    fake = _fake_engine(tmp_path, "partial.sh", """printf '{"hookSpecificOutput":{"permi'; exit 4""")
    r = HookRunner.run(HookRunner.bash_input("git status", HERE), {"GATE_INFRA_PYTHON": fake})
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "plugin-fault: internal error: engine exit 4"


def test_engine_exit_0_without_output_is_no_decision(tmp_path):
    fake = _fake_engine(tmp_path, "noop.sh", "exit 0")
    assert HookRunner.run(HookRunner.bash_input("git status", HERE), {"GATE_INFRA_PYTHON": fake}).stdout == ""


def test_hook_registered_for_bash_and_mcp_only():
    hooks = json.loads((DG / "hooks" / "hooks.json").read_text())["hooks"]
    entries = [e for e in hooks["PreToolUse"] if e["matcher"] == "Bash|mcp__.*"]
    assert len(entries) == 1
    assert re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/gate\.sh", entries[0]["hooks"][0]["command"])
    assert not any(
        e["matcher"] != "Bash|mcp__.*" and any(re.search(r"gate\.sh", h["command"]) for h in e["hooks"])
        for e in hooks["PreToolUse"]
    )


def test_session_start_registered():
    hooks = json.loads((DG / "hooks" / "hooks.json").read_text())["hooks"]
    [entry] = hooks["SessionStart"]
    assert re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/session-start\.sh", entry["hooks"][0]["command"])


def _raw_bash(command: bytes, cwd) -> bytes:
    head = json.dumps({"tool_name": "Bash", "tool_input": {"command": "@@"}, "cwd": str(cwd)}).encode()
    return head.replace(b"@@", command)


def test_non_utf8_stdin_is_decided_normally(run, jev, tmp_path):
    r = run(_raw_bash(b"rm -rf \xff", tmp_path), RISKY)
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert jev.bodies[0]["state"]["command"] == "rm -rf �"
    assert run(_raw_bash(b"ls \xff", tmp_path), SAFE).stdout == ""


def test_hook_does_not_depend_on_the_working_directory(run):
    assert run(HookRunner.bash_input("terraform apply", REPO), RISKY, cwd=HERE).stdout.startswith(ASK_PREFIX)
