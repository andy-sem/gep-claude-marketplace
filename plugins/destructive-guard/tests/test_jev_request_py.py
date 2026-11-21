"""Jev request and Jev layer, in-process (Python twin of test_jev_http.py).

Drives `JevClient.ask_jev` / `run_jev` from destructive_guard.jev.decider against the local JevMock server (real
HTTP) or a fake opener. Every row of test_jev_http.py has its counterpart here; the rule result and the
call are built by hand as the hook would build them.
"""

import json
import time
import urllib.error

import pytest

from destructive_guard.jev.client import JevClient
from destructive_guard.jev.config import JevConfig
from destructive_guard.jev.decider import JevDecider
from destructive_guard.jev.prompt import JevPrompt
from destructive_guard.jev.request import JevRequest
from testkit.jev_mock import probs

DOWN = "http://127.0.0.1:1/v1/systemone"
DBHOST_SQL = "mcp__plugin_dbhost_dbhost__execute_sql"
ISSUE_EDIT = "mcp__tracker__editIssue"

SAFE = probs(0, 1, 0, 0)
RISKY = probs(0, 0, 0, 1)
READ_ONLY = probs(0.01, 0.97, 0.01, 0.01)

TF_RULE = {"decision": "ask", "reason": "terraform: apply"}
DB_RULE = {"decision": "ask", "reason": "dbhost-mcp: execute_sql"}


def bash(command, scripts=None):
    return {"tool": "Bash", "command": command, "scripts": scripts or []}


def mcp(tool, tool_input=None):
    return {"tool": tool, "input": tool_input or {}}


@pytest.fixture
def jev_env(jev, tmp_path):
    log = tmp_path / "audit.jsonl"
    return {
        "GATE_JEV": "1",
        "TYPESAFE_API_KEY": "key-123",
        "GATE_JEV_URL": jev.url,
        "GATE_JEV_PROMPT": "cloud-change",
        "GATE_JEV_LOG": str(log),
        "GATE_JEV_TIMEOUT_MS": "5000",
    }


@pytest.fixture
def go(jev, jev_env, tmp_path):
    """run_jev(call, rule_result, **env) -> (final, audit records)."""
    log = tmp_path / "audit.jsonl"

    def run(call, rule_result=None, **env):
        log.unlink(missing_ok=True)
        cfg = JevConfig.read({**jev_env, **env}, cwd=tmp_path)
        final = JevDecider.run_jev(call, rule_result, cfg)
        records = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return final, records

    return run


# ---------------------------------------------------------------------------
# ask_jev
# ---------------------------------------------------------------------------


def test_request_shape(jev, jev_env, tmp_path):
    p = READ_ONLY
    jev.answer(p, usage={"input_tokens": 900, "output_tokens": 12})
    cfg = JevConfig.read(jev_env, cwd=tmp_path)
    r = JevClient().ask_jev(JevRequest.build_state(bash("git status")), cfg)
    assert r["probabilities"] == p
    assert r["usage"] == {"input_tokens": 900, "output_tokens": 12}
    assert isinstance(r["latencyMs"], int)
    assert jev.hits == 1
    assert jev.headers[0]["authorization"] == "Bearer key-123"
    body = jev.bodies[0]
    assert list(body) == ["model", "state", "questions"]
    assert body["model"] == "jev-latest"
    assert body["state"]["tool"] == "Bash"
    assert body["state"]["command"] == "git status"
    assert sorted(body["state"]["context"]) == ["environment", "inputs", "policy", "project"]
    assert list(body["questions"]) == ["cloud_change"]
    q = body["questions"]["cloud_change"]
    assert q["type"] == "choice"
    assert q["instructions"] == "Does this call change cloud services, remote infrastructure or databases?"
    assert list(q["criteria"]) == ["unrelated", "read_only", "cloud_or_data_change", "destructive"]
    for option in q["criteria"].values():
        assert isinstance(option["description"], str)
        assert len(option["examples"]) > 0
    assert "local_write" not in json.dumps(body)


def test_error_has_latency(jev, go):
    jev.answer(status=500)
    _, [record] = go(bash("ls"))
    assert record["outcome"] == "fallback: http 500"
    assert isinstance(record["latencyMs"], int)


def test_usage_null_when_absent(jev, go):
    jev.answer(kind="raw", body={"answers": {"cloud_change": {"type": "choice", "probabilities": READ_ONLY}}})
    _, [record] = go(bash("ls"))
    assert record["probabilities"] == READ_ONLY
    assert record["usage"] is None


def test_non_retryable_http_error(jev, go):
    jev.answer(status=401)
    _, [record] = go(bash("ls"))
    assert record["outcome"] == "fallback: http 401"
    assert jev.hits == 1


def test_retries_429_then_succeeds(jev, go):
    p = probs(0.97, 0.01, 0.01, 0.01)
    jev.sequence({"status": 429, "retry_after": "0"}, {"probs": p})
    final, [record] = go(bash("terraform apply"), TF_RULE)
    assert jev.hits == 2
    assert record["probabilities"] == p
    assert record["decision"] == "pass"
    assert final is None  # the ok answer lifts the tf rule ask


def test_retry_after_over_budget_gives_up(jev, go):
    jev.answer(status=529, retry_after="10")
    _, [record] = go(bash("ls"), GATE_JEV_TIMEOUT_MS="200")
    assert record["outcome"] == "fallback: http 529"
    assert jev.hits == 1


def test_hang_times_out(jev, go):
    jev.answer(kind="hang")
    started = time.monotonic()
    _, [record] = go(bash("ls"), GATE_JEV_TIMEOUT_MS="50")
    assert record["outcome"] == "fallback: timeout"
    assert time.monotonic() - started < 5


def test_network_failure(go):
    _, [record] = go(bash("ls"), GATE_JEV_URL=DOWN)
    assert record["outcome"] == "fallback: network"


def test_malformed_bodies(jev, go):
    jev.answer(kind="malformed")
    assert go(bash("ls"))[1][0]["outcome"] == "fallback: malformed"
    jev.answer(kind="raw", body={"answers": {}})
    assert go(bash("ls"))[1][0]["outcome"] == "fallback: malformed"


def test_malformed_answer_shapes_never_crash(jev, go):
    for body in [[], {"answers": []}, {"answers": {"cloud_change": {"type": "choice"}}}, {"answers": {"cloud_change": 3}}]:
        jev.answer(kind="raw", body=body)
        assert go(bash("ls"))[1][0]["outcome"] == "fallback: malformed", body


def test_retry_budget_covers_sleeps():
    """Total wall time stays within the budget: a retry-after that does not fit gives up at once."""
    slept = []
    now = [0.0]

    def clock():
        return now[0]

    def sleep(s):
        slept.append(s)
        now[0] += s

    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 429, "busy", {"retry-after": "2"}, None)

    cfg = {"apiKey": "k", "url": "https://x.test/", "model": "m", "timeoutMs": 5000, "prompt": JevPrompt.builtin_prompt("cloud-change")}
    r = JevClient(sleep=sleep).ask_jev({"tool": "Bash", "command": "ls", "scripts": [], "notes": []}, cfg, opener=opener, clock=clock)
    assert r["error"] == "http 429"
    assert slept == [2.0, 2.0]  # a third wait of 2 s would end past the 5 s budget
    assert r["latencyMs"] == 4000


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("refused"),
        ConnectionResetError(),
        OSError("boom"),
        ValueError("x"),
        RuntimeError("x"),
        urllib.error.HTTPError("https://x.test/", 500, "err", {}, None),
        urllib.error.URLError(TimeoutError()),
        TimeoutError(),
    ],
    ids=lambda e: type(e).__name__,
)
def test_ask_jev_never_raises(error):
    def opener(req, timeout):
        raise error

    cfg = {"apiKey": "k", "url": "https://x.test/", "model": "m", "timeoutMs": 500, "prompt": JevPrompt.builtin_prompt("cloud-change")}
    r = JevClient().ask_jev({"tool": "Bash", "command": "ls", "scripts": [], "notes": []}, cfg, opener=opener)
    assert set(r) == {"error", "latencyMs"}
    assert r["error"] in {"network", "timeout", "http 500"}


def test_retry_delay_forms():
    assert JevClient().retry_delay(1, "3") == 3000
    assert JevClient().retry_delay(1, "0") == 0
    assert 100 <= JevClient().retry_delay(1, None) < 150
    assert 200 <= JevClient().retry_delay(2, "garbage") < 250
    assert 200 <= JevClient().retry_delay(2, "-1") < 250
    assert JevClient().retry_delay(1, "Wed, 21 Oct 2015 07:28:00 GMT") == 0  # a past HTTP-date: retry now


# ---------------------------------------------------------------------------
# run_jev
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "env"),
    [({"status": 500}, {}), ({}, {"GATE_JEV_URL": DOWN})],
    ids=["http-500", "network"],
)
def test_failures_keep_rule_result_for_bash_and_mcp(jev, go, answer, env):
    jev.answer(SAFE, **answer)
    for call, rule in [(bash("terraform apply"), TF_RULE), (mcp(DBHOST_SQL, {"query": "SELECT 1"}), DB_RULE)]:
        final, [record] = go(call, rule, **env)
        assert final == rule
        assert record["outcome"].startswith("fallback: ")
    for call in [bash("git status"), mcp(ISSUE_EDIT, {"issueIdOrKey": "PROJ-1"})]:
        final, [record] = go(call, None, **env)
        assert final is None
        assert record["outcome"].startswith("fallback: ")


def test_can_lift_0_mcp(jev, go):
    jev.answer(SAFE)
    assert go(mcp(DBHOST_SQL, {"a": 1}), DB_RULE, GATE_JEV_CAN_LIFT="0")[0] == DB_RULE
    assert go(mcp(ISSUE_EDIT, {"a": 1}), None, GATE_JEV_CAN_LIFT="0")[0] is None
    assert go(mcp(DBHOST_SQL, {"a": 1}), DB_RULE)[0] is None
    jev.answer(RISKY)
    added, _ = go(mcp(ISSUE_EDIT, {"a": 1}), None, GATE_JEV_CAN_LIFT="0")
    assert added["decision"] == "ask"
    assert added["reason"].startswith("jev: ")


def test_env_reference_never_sent(jev, go):
    rule = {"decision": "ask", "reason": "env: cat .env"}
    jev.answer(SAFE)
    final, [record] = go(bash("cat .env"), rule)
    assert jev.hits == 0
    assert final == rule
    assert record["outcome"] == "skipped: .env reference"
    assert record["command"] is None


def test_no_rule_opinion_asks_for_bash_and_mcp(jev, go):
    jev.answer(probs(0, 0.05, 0.05, 0.9))
    for call in [bash("rm -rf x"), mcp("mcp__x__y")]:
        final, _ = go(call, None)
        assert final == {"decision": "ask", "reason": "jev: destructive p=0.90 risk=0.95"}


def test_undecided_keeps_rule_result(jev, go):
    jev.answer(probs(0.04, 0.9, 0.04, 0.02))
    final, [record] = go(bash("terraform apply"), TF_RULE)
    assert jev.hits == 1
    assert final == TF_RULE
    assert record["jev"] is None
    assert record["decision"] == "ask"


def test_bash_payload_exact_scripts_and_no_notes(jev, go):
    jev.answer(READ_ONLY)
    scripts = [{"path": "infra/cloud/apply.sh", "content": "terraform apply\nTOKEN=abcdef\n", "size": 29, "truncated": False}]
    go(bash("bash infra/cloud/apply.sh --apply", scripts))
    state = jev.bodies[0]["state"]
    assert state["tool"] == "Bash"
    assert state["command"] == "bash infra/cloud/apply.sh --apply"
    assert state["scripts"] == [{"path": "infra/cloud/apply.sh", "content": "terraform apply\nTOKEN=[REDACTED]\n"}]
    assert state["notes"] == []


def test_mcp_payload_input_and_cut_note(jev, go):
    jev.answer(READ_ONLY)
    go(mcp(DBHOST_SQL, {"query": "SELECT 1"}))
    state = jev.bodies[0]["state"]
    assert state["tool"] == DBHOST_SQL
    assert state["input"] == '{"query":"SELECT 1"}'
    assert state["notes"] == []
    assert "command" not in state
    text = {"text": "lorem ipsum " * 750}
    go(mcp("mcp__x__y", text))
    state = jev.bodies[1]["state"]
    assert len(state["input"]) == 8000
    full = len(json.dumps(text, separators=(",", ":")))
    assert state["notes"] == [f"input cut to 8000 of {full} characters"]


# ---------------------------------------------------------------------------
# audit log
# ---------------------------------------------------------------------------


def test_audit_log_redacted_records(jev, jev_env, tmp_path):
    log = tmp_path / "audit.jsonl"
    cfg = JevConfig.read(jev_env, cwd=tmp_path)
    jev.answer(probs(0.01, 0.98, 0.005, 0.005), usage={"input_tokens": 1000})
    JevDecider.run_jev(bash("TOPSECRET_X=supersecret123 node a.mjs", [{"path": "a.mjs", "content": "x"}]), None, cfg)
    JevDecider.run_jev(bash("cat .env"), None, cfg)
    JevDecider.run_jev(mcp(DBHOST_SQL, {"password": "supersecret123", "q": 1}), DB_RULE, cfg)
    jev.answer(status=401)
    JevDecider.run_jev(bash("terraform apply"), TF_RULE, cfg)
    text = log.read_text()
    assert "supersecret123" not in text, text
    lines = [json.loads(line) for line in text.strip().split("\n")]
    assert len(lines) == 4
    assert lines[0]["tool"] == "Bash"
    assert lines[0]["command"] == "TOPSECRET_X=[REDACTED] node a.mjs"
    assert lines[0]["scripts"] == ["a.mjs"]
    assert lines[0]["decision"] == "pass"
    assert lines[0]["rule"] is None
    assert lines[0]["usage"] == {"input_tokens": 1000}
    assert isinstance(lines[0]["latencyMs"], int)
    assert lines[0]["probabilities"]["read_only"] == 0.98
    assert lines[0]["ts"].endswith("Z")
    assert lines[1]["command"] is None
    assert lines[1]["outcome"].startswith("skipped")
    assert lines[1]["latencyMs"] == 0
    assert lines[2]["tool"] == DBHOST_SQL
    assert lines[2]["input"] == '{"password":"[REDACTED]","q":1}'
    assert lines[2]["rule"].startswith("dbhost-mcp:")
    assert lines[2]["decision"] == "pass"
    assert lines[3]["outcome"] == "fallback: http 401"
    assert lines[3]["rule"].startswith("terraform:")
    assert isinstance(lines[3]["latencyMs"], int)
