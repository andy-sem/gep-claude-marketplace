"""HookOut: the only writer of PreToolUse output; it cannot say allow or deny (S1) and keeps S3."""

import json

import pytest

from destructive_guard.down import Down
from destructive_guard.outcome import HookOut

OFF = "GATE_ENABLED=0 turns the gate off."


def test_none_is_no_output():
    assert HookOut("none").to_json() is None


def test_ask_bytes():
    assert HookOut("ask", "jev: destructive p=0.90 risk=0.95").to_json() == (
        '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask",'
        '"permissionDecisionReason":"jev: destructive p=0.90 risk=0.95"}}'
    )


def test_ask_with_warning_bytes():
    out = HookOut.unavailable(Down.HTTP, "http 503")
    assert out.to_json() == (
        '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask",'
        '"permissionDecisionReason":"jev-unavailable: http 503"},'
        f'"systemMessage":"destructive-guard: Jev returned http 503; asking you instead. {OFF}"}}'
    )


def test_warning_only_bytes():
    out = HookOut("none", warning=Down.ENV_REFERENCE)
    assert out.to_json() == (
        '{"systemMessage":"destructive-guard: call mentions a .env file and was not sent to Jev; '
        "Claude Code's permissions apply\"}"
    )


@pytest.mark.parametrize(
    ("kind", "detail", "reason", "message"),
    [
        (Down.TIMEOUT, "timeout after 1500 ms", "jev-unavailable: timeout after 1500 ms", f"Jev did not answer in time (1500 ms); asking you instead. {OFF}"),
        (Down.NETWORK, "network error", "jev-unavailable: network error", f"Jev could not be reached; asking you instead. {OFF}"),
        (Down.MALFORMED, "malformed answer", "jev-unavailable: malformed answer", f"Jev's answer was malformed; asking you instead. {OFF}"),
    ],
)
def test_jev_unavailable_texts(kind, detail, reason, message):
    out = HookOut.unavailable(kind, detail)
    assert (out.decision, out.reason, out.message()) == ("ask", reason, f"destructive-guard: {message}")


@pytest.mark.parametrize(
    ("kind", "detail", "reason", "message"),
    [
        (Down.BAD_INPUT, None, "plugin-fault: bad hook input", f"could not read the hook input; asking you instead. {OFF}"),
        (
            Down.PYTHON_MISSING,
            None,
            "plugin-fault: no Python >= 3.14 found (set GATE_INFRA_PYTHON)",
            f"no Python >= 3.14 found (set GATE_INFRA_PYTHON); asking you instead. {OFF}",
        ),
        (Down.INTERNAL_ERROR, "KeyError", "plugin-fault: internal error: KeyError", f"internal error (KeyError); asking you instead. {OFF}"),
    ],
)
def test_plugin_fault_texts(kind, detail, reason, message):
    out = HookOut.fault(kind, detail)
    assert (out.decision, out.reason, out.message()) == ("ask", reason, f"destructive-guard: {message}")


def test_output_never_says_allow_or_deny():
    for out in [HookOut("none"), HookOut("ask", "r"), HookOut.fault(Down.BAD_INPUT), HookOut("none", warning=Down.ENV_REFERENCE)]:
        text = out.to_json()
        assert text is None or ('"allow"' not in text and '"deny"' not in text)
    with pytest.raises(TypeError):
        HookOut("allow", "r", None, None, extra=1)  # type: ignore[call-arg]


def test_ask_needs_a_reason_and_none_cannot_have_one():
    with pytest.raises(ValueError):
        HookOut("ask")
    with pytest.raises(ValueError):
        HookOut("none", "reason")


def test_ask_with_a_warning_that_does_not_ask_raises():
    with pytest.raises(ValueError):
        HookOut("ask", "r", Down.ENV_REFERENCE)


@pytest.mark.parametrize("kind", [d for d in Down if d.asks])
def test_warning_that_asks_needs_ask(kind):
    with pytest.raises(ValueError):
        HookOut("none", warning=kind)


def test_down_classification_matches_the_model():
    assert {d for d in Down if d.jev_unavailable} == {Down.TIMEOUT, Down.HTTP, Down.NETWORK, Down.MALFORMED}
    assert {d for d in Down if d.plugin_fault} == {Down.BAD_INPUT, Down.PYTHON_MISSING, Down.INTERNAL_ERROR}
    assert [d for d in Down if not d.asks] == [Down.ENV_REFERENCE]
    assert json.loads(HookOut.fault(Down.BAD_INPUT).to_json())["hookSpecificOutput"]["permissionDecision"] == "ask"
