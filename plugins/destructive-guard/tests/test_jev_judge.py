"""JevJudge: Jev's answer -> hook output (the model's `judge`)."""

import pytest

from destructive_guard.down import Down
from destructive_guard.jev.judge import JevJudge
from destructive_guard.jev.prompt import JevPrompt
from dg_testkit.jev_mock import JevMock

CFG = {"escalateThreshold": 0.5, "timeoutMs": 1500, "prompt": JevPrompt.builtin_prompt("cloud-change")}


def judge(probs=None, error=None, **cfg):
    result = {"probabilities": probs} if probs else {"error": error}
    return JevJudge.judge(result, {**CFG, **cfg})


def test_risk_sums_the_ask_choices():
    assert JevJudge.risk(JevMock.probs(0.1, 0.2, 0.3, 0.4), CFG["prompt"]) == pytest.approx(0.7)


def test_below_threshold_gives_no_decision():
    out = judge(JevMock.probs(0.5, 0.4, 0.05, 0.05))
    assert (out.decision, out.warning, out.reason) == ("none", None, None)


def test_exactly_at_the_threshold_gives_no_decision():
    assert judge(JevMock.probs(0.25, 0.25, 0.25, 0.25)).decision == "none"


def test_above_threshold_asks_with_top_and_risk():
    out = judge(JevMock.probs(0.1, 0.1, 0.6, 0.2))
    assert (out.decision, out.reason, out.warning) == ("ask", "jev: cloud_or_data_change p=0.60 risk=0.80", None)


def test_tie_goes_to_the_last_choice():
    out = judge(JevMock.probs(0, 0, 0.5, 0.5), escalateThreshold=0.4)
    assert out.reason == "jev: destructive p=0.50 risk=1.00"


def test_lower_threshold_asks_more():
    probs = JevMock.probs(0.6, 0.1, 0.2, 0.1)
    assert judge(probs).decision == "none"
    assert judge(probs, escalateThreshold=0.2).decision == "ask"


@pytest.mark.parametrize(
    ("error", "kind", "reason"),
    [
        ("timeout", Down.TIMEOUT, "jev-unavailable: timeout after 1500 ms"),
        ("http 503", Down.HTTP, "jev-unavailable: http 503"),
        ("http 401", Down.HTTP, "jev-unavailable: http 401"),
        ("network", Down.NETWORK, "jev-unavailable: network error"),
        ("malformed", Down.MALFORMED, "jev-unavailable: malformed answer"),
        ("something else", Down.NETWORK, "jev-unavailable: network error"),
    ],
)
def test_each_error_asks_with_its_warning(error, kind, reason):
    out = judge(error=error)
    assert (out.decision, out.warning, out.reason) == ("ask", kind, reason)
