"""Contract: hooks/gate.sh without Jev (port of gate-hook.test.mjs, non-Jev part)."""

import json
import re

import pytest

from testkit import DG, REPO
from testkit.hook import ASK_TEMPLATE, bash_input, decision, run_hook
from testkit.projects import provision_project, temp_project

HERE = DG / "tests"


@pytest.fixture
def run(impl, tf_rules):
    def go(stdin, env=None):
        return run_hook(impl, stdin, {"GATE_RULES": str(tf_rules), "CLAUDE_PROJECT_DIR": str(REPO)}, env or {})

    return go


@pytest.fixture
def run_shipped(run, shipped_rules):
    return lambda command, cwd: run(bash_input(command, cwd), {"GATE_RULES": str(shipped_rules)})


def _ask(stdout: str) -> dict:
    o = decision(stdout)
    assert o["permissionDecision"] == "ask"
    return o


def _fake_engine(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(f"#!/usr/bin/env bash\n{body}\n")
    p.chmod(0o755)
    return str(p)


def test_gated_command_asks(run):
    r = run(bash_input("terraform apply", HERE))
    assert r.status == 0
    assert _ask(r.stdout)["permissionDecisionReason"].startswith("tf:")


def test_git_status_passes(run):
    r = run(bash_input("git status", HERE))
    assert r.status == 0
    assert r.stdout == ""


def test_non_json_stdin_asks_unparsable(run):
    r = run("not json")
    assert r.status == 0
    assert _ask(r.stdout)["permissionDecisionReason"].startswith("unparsable")


def test_invalid_rules_file_asks_gate_config(run, bad_rules):
    r = run(bash_input("git status", HERE), {"GATE_RULES": str(bad_rules)})
    assert r.status == 0
    assert _ask(r.stdout)["permissionDecisionReason"].startswith("gate-config")


def test_interpreter_unavailable_asks(run, impl):
    r = run(bash_input("git status", HERE), {impl.interpreter_var: "/nonexistent"})
    assert r.status == 0
    assert _ask(r.stdout)["permissionDecisionReason"] == impl.unavailable_reason


def test_engine_partial_json_then_nonzero_gives_fixed_ask(run, impl, tmp_path):
    fake = _fake_engine(tmp_path, "partial.sh", """printf '{"hookSpecificOutput":{"permi'; exit 4""")
    r = run(bash_input("git status", HERE), {impl.interpreter_var: fake})
    assert _ask(r.stdout)["permissionDecisionReason"] == "gate-config: engine failed"


def test_engine_exit_0_without_running_asks(run, impl, tmp_path):
    fake = _fake_engine(tmp_path, "noop.sh", "exit 0")
    r = run(bash_input("git status", HERE), {impl.interpreter_var: fake})
    assert _ask(r.stdout)["permissionDecisionReason"] == "gate-config: engine failed"


def test_empty_stdin_asks(run):
    _ask(run("").stdout)


def test_script_scan_terraform_script_asks(run_shipped, tmp_path):
    root = temp_project(tmp_path, {"infra/cloud/apply.sh": "#!/bin/bash\nterraform -chdir=environments/dev apply dev.tfplan\n"})
    o = _ask(run_shipped("bash infra/cloud/apply.sh --apply", root).stdout)
    assert o["permissionDecisionReason"] == "script: infra/cloud/apply.sh runs terraform"


def test_script_scan_provision_script_importing_cloudctl_asks(run_shipped, tmp_path):
    o = _ask(run_shipped("node scripts/provision-cloud-app-dev.mjs", provision_project(tmp_path)).stdout)
    assert re.match(r"^script: scripts/provision-cloud-app-dev\.mjs ", o["permissionDecisionReason"])


def test_script_scan_cloudflare_only_script_passes(run_shipped, tmp_path):
    root = temp_project(
        tmp_path,
        {"scripts/cf.mjs": 'await fetch("https://api.cloudflare.com/client/v4/x")\nspawn("wrangler", ["deploy"])\n'},
    )
    assert run_shipped("node scripts/cf.mjs", root).stdout == ""


@pytest.mark.parametrize(
    "command",
    ["terraform -chdir=infra/cloud/environments/dev apply dev.tfplan", "terraform destroy", "tofu import a b"],
)
def test_terraform_rule_asks(run_shipped, command):
    assert _ask(run_shipped(command, REPO).stdout)["permissionDecisionReason"].startswith("terraform:")


@pytest.mark.parametrize(
    "command",
    [
        "terraform plan",
        "terraform fmt",
        "terraform validate",
        "cloudctl sql instances create --help",
        "pnpm test:hooks",
        "node scripts/deploy-cloud-app-dev.test.mjs",
        "git push --force",
    ],
)
def test_fallback_passes(run_shipped, command):
    assert run_shipped(command, REPO).stdout == ""


def test_hook_registered_for_bash_and_mcp_only():
    hooks = json.loads((DG / "hooks" / "hooks.json").read_text())["hooks"]
    entries = [e for e in hooks["PreToolUse"] if e["matcher"] == "Bash|mcp__.*"]
    assert len(entries) == 1
    assert re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/hooks/gate\.sh", entries[0]["hooks"][0]["command"])
    assert not any(
        e["matcher"] != "Bash|mcp__.*" and any(re.search(r"gate\.sh", h["command"]) for h in e["hooks"])
        for e in hooks["PreToolUse"]
    )


# --- review focus: exact bytes and non-UTF-8 input ---------------------------


def test_ask_output_exact_bytes(impl, tmp_path):
    engine = run_hook(impl, bash_input("git push -f", tmp_path), cwd=tmp_path)
    assert engine.status == 0
    assert engine.stdout == (
        '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask",'
        '"permissionDecisionReason":"git-push-force: gated invocation"}}'
    )
    assert engine.stdout == ASK_TEMPLATE.format("git-push-force: gated invocation")
    wrapper = run_hook(impl, bash_input("git status", tmp_path), {impl.interpreter_var: "/nonexistent"}, cwd=tmp_path)
    assert wrapper.stdout == ASK_TEMPLATE.format(impl.unavailable_reason)


def _raw_bash(command: bytes, cwd) -> bytes:
    head = json.dumps({"tool_name": "Bash", "tool_input": {"command": "@@"}, "cwd": str(cwd)}).encode()
    return head.replace(b"@@", command)


def test_non_utf8_stdin_decides_normally(impl, tmp_path):
    r = run_hook(impl, _raw_bash(b"rm -rf \xff", tmp_path), cwd=tmp_path)
    assert r.stdout == ASK_TEMPLATE.format("rm-recursive-force: gated invocation")
    assert run_hook(impl, _raw_bash(b"ls \xff", tmp_path), cwd=tmp_path).stdout == ""
    r = run_hook(impl, _raw_bash("rm -rf Für".encode(), tmp_path), cwd=tmp_path)
    assert decision(r.stdout)["permissionDecision"] == "ask"
