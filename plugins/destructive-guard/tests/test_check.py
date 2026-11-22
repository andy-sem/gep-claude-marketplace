"""Contract: the check CLI (interim shape; L4 finishes it on the Jev hook path)."""

import json
import re

import pytest

from testkit.check_cli import CheckRunner
from testkit.jev_mock import JevMock

RISKY = JevMock.probs(0.1, 0.1, 0.6, 0.2)
SAFE = JevMock.probs(0.01, 0.97, 0.01, 0.01)


def check_json(impl, *args, env=None, cwd=None):
    proc = CheckRunner.run_check(impl, "--json", *args, env=env or {}, cwd=cwd)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture
def jev_env(jev):
    return {"TYPESAFE_API_KEY": "sekret-123", "GATE_JEV_URL": jev.url, "GATE_JEV_PROMPT": "cloud-change"}


def test_parse_args_command_mcp_and_config(impl, jev, jev_env, tmp_path):
    jev.answer(SAFE)
    assert check_json(impl, "git push -f", env=jev_env, cwd=tmp_path)["command"] == "git push -f"
    assert check_json(impl, "--", "rm", "-rf", "x", env=jev_env, cwd=tmp_path)["command"] == "rm -rf x"
    m = check_json(impl, "--mcp", "mcp__db__q", '{"a":1}', env=jev_env, cwd=tmp_path)
    assert (m["tool"], m["input"]) == ("mcp__db__q", {"a": 1})
    assert check_json(impl, "--mcp", "mcp__x__y", env=jev_env, cwd=tmp_path)["input"] == {}
    assert "jev" in check_json(impl, cwd=tmp_path)
    assert "jev" in check_json(impl, "--config", cwd=tmp_path)


@pytest.mark.parametrize(
    "argv",
    [["--nope"], ["--mcp"], ["--mcp", "Bash"], ["--mcp", "mcp__x__y", "{"], ["--mcp", "mcp__x__y", "[1]"], ["--"], ["--cwd", "x"]],
    ids=json.dumps,
)
def test_usage_errors_exit_2(impl, argv):
    proc = CheckRunner.run_check(impl, *argv)
    assert proc.returncode == 2
    assert re.match(r"^usage error: ", proc.stdout)


def test_jev_option_is_gone(impl):
    proc = CheckRunner.run_check(impl, "--jev", "ls")
    assert proc.returncode == 2
    assert "no longer needed" in proc.stdout


def test_risky_call_asks_and_safe_call_has_no_decision(impl, jev, jev_env, tmp_path):
    jev.answer(RISKY)
    r = check_json(impl, "terraform apply", env=jev_env, cwd=tmp_path)
    assert (r["decision"], r["reason"]) == ("ask", "jev: cloud_or_data_change p=0.60 risk=0.80")
    assert r["risk"] == pytest.approx(0.8)
    assert jev.hits == 1
    jev.answer(SAFE)
    r = check_json(impl, "--mcp", "mcp__db__execute_sql", '{"query":"SELECT 1"}', env=jev_env, cwd=tmp_path)
    assert (r["decision"], r["reason"]) == ("none", None)


def test_unavailable_jev_asks_with_a_warning(impl, jev, jev_env, tmp_path):
    jev.answer(kind="status", status=503)
    r = check_json(impl, "ls", env=jev_env, cwd=tmp_path)
    assert r["decision"] == "ask"
    assert r["reason"].startswith("jev-unavailable: http 503")
    assert "asking you instead" in r["warning"]


def test_env_file_call_is_not_sent(impl, jev, jev_env, tmp_path):
    r = check_json(impl, "cat .env", env=jev_env, cwd=tmp_path)
    assert r["decision"] == "none"
    assert ".env" in r["warning"]
    assert jev.hits == 0


def test_disabled_and_misconfigured_do_not_contact_jev(impl, jev, jev_env, tmp_path):
    off = check_json(impl, "git push -f", env={**jev_env, "GATE_ENABLED": "0"}, cwd=tmp_path)
    assert off["decision"] == "none"
    assert "disabled" in off["reason"]
    nokey = check_json(impl, "git push -f", cwd=tmp_path)
    assert nokey["decision"] == "none"
    assert nokey["warning"].startswith("misconfigured: ")
    assert jev.hits == 0


def test_effective_config_redacts_the_key(impl, tmp_path):
    env = {"TYPESAFE_API_KEY": "sekret-123"}
    proc = CheckRunner.run_check(impl, "--json", "--config", env=env, cwd=tmp_path)
    j = json.loads(proc.stdout)
    assert (j["enabled"], j["envGuard"], j["log"]) == (True, True, None)
    assert j["jev"]["apiKey"] == "[set]"
    assert j["jev"]["prompt"] == "destructive"
    assert j["sessionWarning"] is None
    assert "sekret-123" not in proc.stdout
    nokey = check_json(impl, "--config", cwd=tmp_path)
    assert nokey["jev"]["apiKey"] == "[missing]"
    assert "TYPESAFE_API_KEY" in nokey["sessionWarning"]
    bad = check_json(impl, "--config", env={"GATE_JEV_TIMEOUT_MS": "x", **env}, cwd=tmp_path)
    assert bad["jev"]["error"].startswith("GATE_JEV_TIMEOUT_MS")


def test_text_output_never_prints_the_key(impl, jev, jev_env, tmp_path):
    jev.answer(RISKY)
    text = CheckRunner.run_check(impl, "git push --force", env=jev_env, cwd=tmp_path)
    assert text.returncode == 0
    assert re.search(r"decision: ask", text.stdout)
    conf = CheckRunner.run_check(impl, env=jev_env, cwd=tmp_path)
    assert re.search(r"api key \[set\]", conf.stdout)
    assert "sekret-123" not in text.stdout + conf.stdout
