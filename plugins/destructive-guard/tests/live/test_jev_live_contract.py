"""The real Jev API still accepts our requests and answers in the shape we parse."""

import math

import pytest

from destructive_guard.jev.prompt import JevPrompt
from testkit.live_jev import LiveJev

pytestmark = pytest.mark.live_jev

BASH = {"tool": "Bash", "command": "git status"}
MCP = {"tool": "mcp__db__execute_sql", "input": {"query": "SELECT count(*) FROM orders"}}


@pytest.mark.parametrize("name", ["destructive", "cloud-change"])
def test_builtin_prompt_is_accepted(live_env, name):
    env = {**live_env, "GATE_JEV_PROMPT": name}
    cfg, _state, result = LiveJev.raw(BASH, env)
    assert "error" not in result, result
    probs = result["probabilities"]
    assert set(probs) == set(JevPrompt.builtin_prompt(name)["criteria"])
    assert math.isclose(sum(probs.values()), 1, abs_tol=0.05)
    assert cfg["prompt"]["question"]


def test_usage_has_integer_token_counts(live_env):
    _cfg, _state, result = LiveJev.raw(BASH, live_env)
    usage = result["usage"]
    assert isinstance(usage, dict), usage
    counts = [v for v in usage.values() if isinstance(v, int) and not isinstance(v, bool)]
    assert counts, usage


@pytest.mark.parametrize("call", [BASH, MCP], ids=["bash", "mcp"])
def test_both_state_shapes_get_an_answer(live_env, call):
    result = LiveJev.decide(call, live_env)
    assert result["error"] is None, result
    assert result["decision"] in ("ask", "none")


def test_command_at_the_cap_is_accepted(live_env):
    command = ("echo " + "lorem ipsum " * 900)[:9000]
    _cfg, state, result = LiveJev.raw({"tool": "Bash", "command": command}, live_env)
    assert len(state["command"]) == 8000
    assert any("command cut" in n for n in state["notes"])
    assert "error" not in result, result


def test_wrong_key_is_an_http_error_never_probabilities(live_env):
    result = LiveJev.decide(BASH, {**live_env, "TYPESAFE_API_KEY": "invalid"})
    assert result["error"] in ("http 401", "http 403"), result
    assert result["probabilities"] is None
    LiveJev.report("contract", "wrong key answers", result["error"])


def test_latency_of_ten_sequential_calls(live_env):
    times = sorted(LiveJev.decide(BASH, live_env)["latencyMs"] for _ in range(10))
    p50 = times[len(times) // 2]
    p95 = times[min(len(times) - 1, math.ceil(0.95 * len(times)) - 1)]
    LiveJev.report("contract", "latency p50 / p95 (ms)", f"{p50} / {p95}")
    print(f"latency p50={p50} ms p95={p95} ms")
    assert p95 <= 1500 * 3, f"p95 {p95} ms: the default 1500 ms budget would time out most calls"
