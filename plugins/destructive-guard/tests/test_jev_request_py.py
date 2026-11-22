"""Jev request and the hook's decision, in-process (Python twin of test_jev_http.py).

Drives `JevClient.ask_jev` and `GateHook.decide` against the local JevMock server (real HTTP) or a fake
opener. The call is built by hand as the hook would build it.
"""

import json
import time
import urllib.error

import pytest

from destructive_guard.hook import GateHook
from destructive_guard.jev.client import JevClient
from destructive_guard.jev.config import JevConfig
from destructive_guard.jev.prompt import JevPrompt
from destructive_guard.jev.request import JevRequest
from testkit.jev_mock import JevMock

DOWN = "http://127.0.0.1:1/v1/systemone"
DBHOST_SQL = "mcp__plugin_dbhost_dbhost__execute_sql"
ISSUE_EDIT = "mcp__tracker__editIssue"

SAFE = JevMock.probs(0, 1, 0, 0)
RISKY = JevMock.probs(0, 0, 0, 1)
READ_ONLY = JevMock.probs(0.01, 0.97, 0.01, 0.01)

def bash(command):
    return {"tool": "Bash", "command": command}


def mcp(tool, tool_input=None):
    return {"tool": tool, "input": tool_input or {}}


@pytest.fixture
def jev_env(jev, tmp_path):
    return {
        "TYPESAFE_API_KEY": "key-123",
        "GATE_JEV_URL": jev.url,
        "GATE_JEV_PROMPT": "cloud-change",
        "GATE_JEV_TIMEOUT_MS": "5000",
    }


@pytest.fixture
def go(jev, jev_env, tmp_path):
    """decide(call, **env) -> (HookOut, the record GATE_LOG would get)."""

    def run(call, **env):
        cfg = JevConfig.read({**jev_env, **env}, cwd=tmp_path)
        record: dict = {}
        return GateHook.decide(call, cfg, record), record

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
    out, record = go(bash("ls"))
    assert out.reason == "jev-unavailable: http 500"
    assert isinstance(record["latencyMs"], int)


def test_usage_null_when_absent(jev, go):
    jev.answer(kind="raw", body={"answers": {"cloud_change": {"type": "choice", "probabilities": READ_ONLY}}})
    _, record = go(bash("ls"))
    assert record["probabilities"] == READ_ONLY
    assert record["usage"] is None


def test_non_retryable_http_error(jev, go):
    jev.answer(status=401)
    out, _ = go(bash("ls"))
    assert out.reason == "jev-unavailable: http 401"
    assert jev.hits == 1


def test_retries_429_then_succeeds(jev, go):
    jev.sequence({"status": 429, "retry_after": "0"}, {"probs": SAFE})
    out, record = go(bash("terraform apply"))
    assert jev.hits == 2
    assert record["probabilities"] == SAFE
    assert out.decision == "none"
    assert out.warning is None


def test_retry_after_over_budget_gives_up(jev, go):
    jev.answer(status=529, retry_after="10")
    out, _ = go(bash("ls"), GATE_JEV_TIMEOUT_MS="200")
    assert out.reason == "jev-unavailable: http 529"
    assert jev.hits == 1


def test_hang_times_out(jev, go):
    jev.answer(kind="hang")
    started = time.monotonic()
    out, _ = go(bash("ls"), GATE_JEV_TIMEOUT_MS="50")
    assert out.reason == "jev-unavailable: timeout after 50 ms"
    assert time.monotonic() - started < 5


def test_network_failure(go):
    out, _ = go(bash("ls"), GATE_JEV_URL=DOWN)
    assert out.reason == "jev-unavailable: network error"


def test_malformed_bodies(jev, go):
    jev.answer(kind="malformed")
    assert go(bash("ls"))[0].reason == "jev-unavailable: malformed answer"
    jev.answer(kind="raw", body={"answers": {}})
    assert go(bash("ls"))[0].reason == "jev-unavailable: malformed answer"


def test_malformed_answer_shapes_never_crash(jev, go):
    for body in [[], {"answers": []}, {"answers": {"cloud_change": {"type": "choice"}}}, {"answers": {"cloud_change": 3}}]:
        jev.answer(kind="raw", body=body)
        assert go(bash("ls"))[0].reason == "jev-unavailable: malformed answer", body


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
    r = JevClient(sleep=sleep).ask_jev({"tool": "Bash", "command": "ls", "notes": []}, cfg, opener=opener, clock=clock)
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
    r = JevClient().ask_jev({"tool": "Bash", "command": "ls", "notes": []}, cfg, opener=opener)
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
# GateHook.decide
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "env"),
    [({"status": 500}, {}), ({}, {"GATE_JEV_URL": DOWN})],
    ids=["http-500", "network"],
)
def test_failures_ask_for_bash_and_mcp(jev, go, answer, env):
    jev.answer(SAFE, **answer)
    for call in [bash("git status"), mcp(DBHOST_SQL, {"query": "SELECT 1"}), mcp(ISSUE_EDIT, {"issueIdOrKey": "PROJ-1"})]:
        out, _ = go(call, **env)
        assert out.decision == "ask"
        assert out.reason.startswith("jev-unavailable: ")
        assert out.warning.jev_unavailable


def test_env_reference_never_sent(jev, go):
    jev.answer(SAFE)
    out, record = go(bash("cat .env"))
    assert jev.hits == 0
    assert out.decision == "none"
    assert out.warning == "envReference"
    assert record["command"] is None
    out, _ = go(mcp(DBHOST_SQL, {"path": "apps/web/.env.local"}))
    assert (out.decision, out.warning, jev.hits) == ("none", "envReference", 0)


def test_risky_answer_asks_for_bash_and_mcp(jev, go):
    jev.answer(JevMock.probs(0, 0.05, 0.05, 0.9))
    for call in [bash("rm -rf x"), mcp("mcp__x__y")]:
        out, _ = go(call)
        assert (out.decision, out.reason) == ("ask", "jev: destructive p=0.90 risk=0.95")


def test_uncertain_answer_gives_no_decision(jev, go):
    jev.answer(JevMock.probs(0.04, 0.9, 0.04, 0.02))
    out, record = go(bash("terraform apply"))
    assert jev.hits == 1
    assert (out.decision, out.warning) == ("none", None)
    assert record["risk"] == pytest.approx(0.06)


def test_bash_payload_is_the_redacted_text_only(jev, go):
    jev.answer(READ_ONLY)
    go(bash("bash infra/cloud/apply.sh --apply TOKEN=abcdef"))
    state = jev.bodies[0]["state"]
    assert state["tool"] == "Bash"
    assert state["command"] == "bash infra/cloud/apply.sh --apply TOKEN=[REDACTED]"
    assert "scripts" not in state
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
