"""The real gate.sh against the Lean model (formal/SimpleGate.lean): theses S1-S10 and one test per `example`.

`model` is the Lean `hook` in Python, per mille like the model. Every run goes through the real hook
with `JevMock`, and each output is checked against the model and against the theses.
"""

import json
import re
import stat
import sys
from dataclasses import dataclass
from itertools import product

import pytest

from testkit import DG
from testkit.hook import HookRunner
from testkit.jev_mock import JevMock

ESCALATE = 500
DOWN_URL = "http://127.0.0.1:1/v1/systemone"
LIB = DG / "lib"
SECRETS = ["abc123xyz", "hunter2", "abcdefSECRET", "pw9"]
SECRET_BASH = "curl -H 'Authorization: Bearer abcdefSECRET' https://user:pw9@host/x TOKEN=abc123xyz ls"
SECRET_MCP = {"query": "SELECT 1", "password": "hunter2"}

# Perm order of the model: allow < ask < deny.
RANK = {"allow": 0, "ask": 1, "deny": 2}


def effective(decision: str, claude: str) -> str:
    """The model's `effective`: a hook decision on top of Claude Code's own permission."""
    if decision == "none":
        return claude
    return "deny" if claude == "deny" else "ask"


ASKS = {"timeout", "http", "network", "malformed", "badInput", "pythonMissing", "internalError"}


def model(setting: str, call: str, q: tuple[str, object]) -> tuple[str, str | None]:
    """The Lean `hook`: (decision, warning). `call` is tool | env | badInput | pythonMissing | crash."""
    if call in ("badInput", "pythonMissing"):
        return "ask", call
    if call == "crash":
        return "ask", "internalError"
    if setting == "misconfigured":
        return "none", None
    if call == "env":
        return "none", "envReference"
    kind, value = q
    if kind == "down":
        return "ask", str(value)
    return ("ask", None) if int(value) > ESCALATE else ("none", None)  # type: ignore[arg-type]


WARNING_TEXT = [
    ("Jev did not answer in time", "timeout"),
    ("Jev returned http", "http"),
    ("Jev could not be reached", "network"),
    ("Jev's answer was malformed", "malformed"),
    ("mentions a .env file", "envReference"),
    ("could not read the hook input", "badInput"),
    ("no Python >= 3.14 found", "pythonMissing"),
    ("internal error", "internalError"),
]


@dataclass
class Out:
    stdout: str
    decision: str  # none | ask
    warning: str | None
    reason: str | None


def read(stdout: str) -> Out:
    """Parses one raw stdout and checks S1 and the raw-stdout scan on the way."""
    if stdout == "":
        return Out(stdout, "none", None, None)
    # S5/S1: the raw bytes never contain a way to allow, deny or stop anything.
    assert not re.search(r'"(allow|deny)"', stdout), stdout
    for forbidden in ("continue", "stopReason", "updatedInput", "additionalContext", '"decision"', "suppressOutput"):
        assert forbidden not in stdout, (forbidden, stdout)
    data = json.loads(stdout)
    assert set(data) <= {"hookSpecificOutput", "systemMessage"}, data
    specific = data.get("hookSpecificOutput")
    decision, reason = "none", None
    if specific is not None:
        assert set(specific) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}, specific
        assert specific["hookEventName"] == "PreToolUse"
        assert specific["permissionDecision"] == "ask"  # S1
        decision, reason = "ask", specific["permissionDecisionReason"]
        assert reason
    warning = None
    message = data.get("systemMessage")
    if message is not None:
        assert message.startswith("destructive-guard: ")
        warning = next(kind for text, kind in WARNING_TEXT if text in message)
    return Out(stdout, decision, warning, reason)


def check_theses(out: Out, expected: tuple[str, str | None], sent: bool, answered: bool) -> None:
    decision, warning = expected
    assert (out.decision, out.warning) == (decision, warning)
    # S3: a warning comes with ask exactly for the Jev and plugin faults; the .env warning has no decision.
    if out.warning is not None:
        assert (out.decision == "ask") == (out.warning in ASKS)
    # S5: the plugin only adds prompts, whatever Claude Code would have done.
    for claude, rank in RANK.items():
        assert RANK[effective(out.decision, claude)] >= rank
    # S4: with no decision the final permission is Claude Code's own.
    if out.decision == "none":
        assert all(effective("none", c) == c for c in RANK)
    # S8: an answered call never warns.
    if answered:
        assert out.warning is None
    del sent


@pytest.fixture
def hook(impl, jev):
    """run(setting, stdin, answer, env) -> Out; `answer` is mock kwargs."""

    def run(setting, stdin, answer=None, env=None):
        if answer is not None:
            jev.answer(**answer)
        base = {"GATE_JEV_PROMPT": "cloud-change", "GATE_JEV_TIMEOUT_MS": "300"}
        if setting == "on":
            base |= {"TYPESAFE_API_KEY": "test-key", "GATE_JEV_URL": jev.url}
        elif setting == "noKey":
            base |= {"GATE_JEV_URL": jev.url}
        elif setting == "badUrl":
            base |= {"TYPESAFE_API_KEY": "test-key", "GATE_JEV_URL": "http://example.com"}
        r = HookRunner.run(impl, stdin, base, env or {})
        assert r.status == 0
        return read(r.stdout)

    return run


# Jev behaviours: name -> (mock kwargs, extra env, the model's q).
JEV = {
    "timeout": ({"kind": "hang"}, {}, ("down", "timeout")),
    "http500": ({"status": 500}, {}, ("down", "http")),
    "http429-over-budget": ({"status": 429, "retry_after": "10"}, {}, ("down", "http")),
    "network": ({"probs": JevMock.probs(1, 0, 0, 0)}, {"GATE_JEV_URL": DOWN_URL}, ("down", "network")),
    "malformed": ({"kind": "malformed"}, {}, ("down", "malformed")),
    "risk-0": ({"probs": JevMock.probs(1, 0, 0, 0)}, {}, ("answer", 0)),
    "risk-eq-escalate": ({"probs": JevMock.probs(0.25, 0.25, 0.25, 0.25)}, {}, ("answer", 500)),
    "risk-gt-escalate": ({"probs": JevMock.probs(0.2, 0.2, 0.3, 0.3)}, {}, ("answer", 600)),
}
ANSWERING = ("risk-0", "risk-eq-escalate", "risk-gt-escalate")
TOOLS = {
    "bash": HookRunner.bash_input(SECRET_BASH, "/tmp"),
    "mcp": HookRunner.mcp_input("mcp__db__execute_sql", SECRET_MCP, "/tmp"),
}
ENV_CALLS = {
    "bash-env": HookRunner.bash_input("cat apps/web/.env.local", "/tmp"),
    "mcp-env": HookRunner.mcp_input("mcp__db__execute_sql", {"query": "select 1", "file": ".env"}, "/tmp"),
}


def bodies_are_clean(jev) -> None:
    """S7: the mock never saw `.env` or a secret."""
    sent = json.dumps(jev.bodies)
    assert ".env" not in sent
    for secret in SECRETS:
        assert secret not in sent, secret


@pytest.mark.parametrize("setting", ["on", "noKey", "badUrl"])
@pytest.mark.parametrize("jev_case", list(JEV))
@pytest.mark.parametrize("tool", list(TOOLS))
def test_gated_calls(hook, jev, setting, jev_case, tool):
    answer, extra, q = JEV[jev_case]
    out = hook(setting, TOOLS[tool], answer, extra if setting == "on" else {})
    expected = model("on" if setting == "on" else "misconfigured", "tool", q)
    check_theses(out, expected, sent=setting == "on", answered=q[0] == "answer")
    if setting == "on":
        bodies_are_clean(jev)
        # S10: Jev on, call sent, Jev unavailable -> never silent.
        if q[0] == "down":
            assert out.decision == "ask"
            assert out.reason.startswith("jev-unavailable: ")
        if q == ("answer", 600):
            assert out.reason.startswith("jev: ")
    else:
        # S9: a misconfigured setting is silent per call and sends nothing.
        assert out.stdout == ""
        assert jev.hits == 0


@pytest.mark.parametrize("setting", ["on", "noKey", "badUrl"])
@pytest.mark.parametrize("call", list(ENV_CALLS))
def test_env_calls_are_never_sent(hook, jev, setting, call):
    out = hook(setting, ENV_CALLS[call], JEV["risk-gt-escalate"][0])
    check_theses(out, model("on" if setting == "on" else "misconfigured", "env", ("answer", 600)), False, False)
    assert jev.hits == 0
    if setting == "on":
        assert out.decision == "none" and out.warning == "envReference"


@pytest.mark.parametrize("setting", ["on", "noKey", "badUrl"])
def test_non_gated_tool_needs_nothing(hook, jev, setting):
    out = hook(setting, json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x"}}), JEV["risk-gt-escalate"][0])
    assert out.stdout == ""
    assert jev.hits == 0


@pytest.mark.parametrize("setting", ["on", "noKey", "badUrl"])
@pytest.mark.parametrize("stdin", ["not json", "", "[1]"])
def test_bad_stdin_asks_whatever_the_setting(hook, jev, setting, stdin):
    out = hook(setting, stdin, JEV["risk-0"][0])
    check_theses(out, model("on" if setting == "on" else "misconfigured", "badInput", ("answer", 0)), False, False)
    assert out.reason == "plugin-fault: bad hook input"
    assert jev.hits == 0


@pytest.mark.parametrize("setting", ["on", "noKey"])
def test_no_python_asks_whatever_the_setting(hook, impl, setting):
    out = hook(setting, TOOLS["bash"], None, {impl.interpreter_var: "/nonexistent"})
    check_theses(out, model("on", "pythonMissing", ("answer", 0)), False, False)
    assert out.reason == "plugin-fault: no Python >= 3.14 found (set GATE_INFRA_PYTHON)"


@pytest.mark.parametrize("setting", ["on", "noKey"])
def test_python_below_3_14_asks(hook, impl, old_python, setting):
    out = hook(setting, TOOLS["bash"], None, {impl.interpreter_var: old_python})
    assert (out.decision, out.warning) == ("ask", "pythonMissing")


@pytest.mark.parametrize("setting", ["on", "noKey"])
def test_engine_exit_1_with_partial_stdout_asks_and_drops_the_partial(hook, impl, tmp_path, setting):
    fake = tmp_path / "partial.sh"
    fake.write_text("#!/bin/sh\nprintf '{\"hookSpecificOutput\":{\"permissionDecision\":\"all'\nexit 1\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    out = hook(setting, TOOLS["bash"], None, {impl.interpreter_var: str(fake)})
    check_theses(out, model("on", "crash", ("answer", 0)), False, False)
    assert out.reason == "plugin-fault: internal error: engine exit 1"
    assert "allow" not in out.stdout


@pytest.mark.parametrize("setting", ["on", "noKey"])
def test_engine_exception_asks(hook, impl, tmp_path, setting):
    """An exception inside the hook (here: while reading the call) is an internal-error ask."""
    fake = tmp_path / "boom.sh"
    code = (
        f"import sys; sys.path.insert(0, {str(LIB)!r}); from destructive_guard.hook import GateHook, main\n"
        "def boom(data):\n    raise RuntimeError('boom')\n"
        "GateHook.call_of = staticmethod(boom); sys.exit(main())"
    )
    fake.write_text(f"#!/bin/sh\nexec {sys.executable} -I -c \"$CODE\"\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    out = hook(setting, TOOLS["bash"], None, {impl.interpreter_var: str(fake), "CODE": code})
    check_theses(out, model("on", "crash", ("answer", 0)), False, False)
    assert out.reason == "plugin-fault: internal error: RuntimeError"


def test_s6_lowering_the_threshold_never_removes_an_ask(hook):
    answer = {"probs": JevMock.probs(0.4, 0.2, 0.2, 0.2)}  # risk 0.4
    assert hook("on", TOOLS["bash"], answer).decision == "none"
    for threshold in ("0.4", "0.3", "0.1"):
        assert hook("on", TOOLS["bash"], answer, {"GATE_JEV_ESCALATE_THRESHOLD": threshold}).decision == ("none" if threshold == "0.4" else "ask")


def test_model_matches_its_own_matrix_exhaustively():
    """The Python model is total over the Lean types and obeys S2 (the only ways to a prompt)."""
    for setting, call, q in product(
        ["on", "misconfigured"],
        ["tool", "env", "badInput", "pythonMissing", "crash"],
        [("answer", 0), ("answer", 500), ("answer", 501), *[("down", d) for d in ("timeout", "http", "network", "malformed")]],
    ):
        decision, _ = model(setting, call, q)
        by_s2 = (
            call in ("badInput", "pythonMissing", "crash")
            or (call == "tool" and setting == "on" and (q[0] == "down" or int(q[1]) > ESCALATE))  # type: ignore[arg-type]
        )
        assert (decision == "ask") == by_s2


# One test per `example` of SimpleGate.lean (same names); the model is checked, and where the hook can
# be driven the real hook too.
EXAMPLES = {
    "answer_0": ("on", "tool", ("answer", 0), ("none", None)),
    "answer_500": ("on", "tool", ("answer", 500), ("none", None)),
    "answer_501": ("on", "tool", ("answer", 501), ("ask", None)),
    "down_timeout": ("on", "tool", ("down", "timeout"), ("ask", "timeout")),
    "down_http": ("on", "tool", ("down", "http"), ("ask", "http")),
    "down_network": ("on", "tool", ("down", "network"), ("ask", "network")),
    "down_malformed": ("on", "tool", ("down", "malformed"), ("ask", "malformed")),
    "misconfigured_no_key_silent": ("misconfigured", "tool", ("answer", 900), ("none", None)),
    "env_mention_not_sent": ("on", "env", ("answer", 900), ("none", "envReference")),
    "bad_input_on": ("on", "badInput", ("answer", 0), ("ask", "badInput")),
    "bad_input_misconfigured": ("misconfigured", "badInput", ("answer", 0), ("ask", "badInput")),
    "python_missing": ("on", "pythonMissing", ("answer", 0), ("ask", "pythonMissing")),
    "crash": ("on", "crash", ("answer", 0), ("ask", "internalError")),
}
LIVE_CASE = {
    "answer_0": ("on", "bash", "risk-0"),
    "answer_500": ("on", "bash", "risk-eq-escalate"),
    "answer_501": ("on", "bash", "risk-gt-escalate"),
    "down_timeout": ("on", "bash", "timeout"),
    "down_http": ("on", "bash", "http500"),
    "down_network": ("on", "bash", "network"),
    "down_malformed": ("on", "bash", "malformed"),
    "misconfigured_no_key_silent": ("noKey", "bash", "risk-gt-escalate"),
}


@pytest.mark.parametrize("name", list(EXAMPLES))
def test_example(name, hook):
    setting, call, q, expected = EXAMPLES[name]
    assert model(setting, call, q) == expected
    if name in LIVE_CASE:
        s, tool, jev_case = LIVE_CASE[name]
        answer, extra, _ = JEV[jev_case]
        out = hook(s, TOOLS[tool], answer, extra)
        assert (out.decision, out.warning) == expected
    elif name == "env_mention_not_sent":
        out = hook("on", ENV_CALLS["bash-env"], JEV["risk-gt-escalate"][0])
        assert (out.decision, out.warning) == expected
    elif name in ("bad_input_on", "bad_input_misconfigured"):
        out = hook("on" if name.endswith("on") else "noKey", "not json", None)
        assert (out.decision, out.warning) == expected


def test_example_session_start_misconfigured_no_key(impl):
    r = HookRunner.run_session(impl)
    assert "TYPESAFE_API_KEY is not set" in json.loads(r.stdout)["systemMessage"]


def test_example_session_start_on_is_silent(impl):
    assert HookRunner.run_session(impl, {"TYPESAFE_API_KEY": "k"}).stdout == ""


@pytest.mark.parametrize(
    ("decision", "claude", "expected"),
    [("ask", "allow", "ask"), ("ask", "deny", "deny"), ("none", "allow", "allow")],
    ids=["effective_ask_allow", "effective_ask_deny", "effective_none_allow"],
)
def test_example_effective(decision, claude, expected):
    assert effective(decision, claude) == expected
