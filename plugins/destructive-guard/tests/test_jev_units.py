"""Jev pure helpers (port of gate-jev.test.mjs, pure part).

Runs in-process against destructive_guard.jev.decider. askJev / runJev rows are in test_jev_http.py
(through the hook) and test_jev_request_py.py (in-process).
"""

import json

import pytest

from destructive_guard.errors import JevConfigError
from destructive_guard.jev.config import JevConfig
from destructive_guard.jev.decider import JevDecider
from destructive_guard.jev.prompt import JevPrompt
from destructive_guard.jev.redactor import Redactor
from destructive_guard.jev.request import JevRequest
from testkit.jev_mock import probs

BASE_ENV = {"GATE_JEV": "1", "TYPESAFE_API_KEY": "key-123"}
JEV_URL = "https://api.typesafe.ai/v1/systemone"
# The JS `cfg` without `logPath`; the ported tests exercise the cloud-change preset.
CFG = {
    "apiKey": "key-123",
    "url": "https://example.test/v1",
    "model": "jev-latest",
    "timeoutMs": 500,
    "allowThreshold": 0.95,
    "escalateThreshold": 0.5,
    "prompt": JevPrompt.builtin_prompt("cloud-change"),
}


def jev_many(fn, *arg_lists):
    owner = JevConfig if fn in ("read",) else Redactor if fn.startswith("redact") else JevRequest if fn in ("parse_answer", "build_state") else JevDecider
    return [getattr(owner, fn)(*args) for args in arg_lists]


def answer(p):
    return {"answers": {"cloud_change": {"type": "choice", "probabilities": p}}}


def bash_call(command, scripts=None):
    return {"tool": "Bash", "command": command, "scripts": scripts or []}


def jev_config_error(env):
    with pytest.raises(JevConfigError):
        JevConfig.read(env)


# ---------------------------------------------------------------------------
# redact
# ---------------------------------------------------------------------------


def redact_many(*commands):
    return jev_many("redact", *([c] for c in commands))


def test_redact_returns_null_for_env_file_references():
    assert redact_many("cat .env", "cat apps/x/.env.local", "source .envrc") == [None, None, None]


def test_redact_strips_url_credentials():
    assert redact_many("git clone https://u:p@host/repo.git") == ["git clone https://[REDACTED]@host/repo.git"]


def test_redact_strips_bearer_basic_token_values():
    schemes = ["Bearer", "Basic", "Token"]
    *outs, plain = redact_many(*(f"curl -H 'Authorization: {s} sekret123' x" for s in schemes), "echo Bearer abc123")
    for out in outs:
        assert "sekret123" not in out, out
        assert "[REDACTED]" in out, out
    assert plain == "echo Bearer [REDACTED]"


def test_redact_strips_secret_named_assignments():
    assert redact_many("run api_key=abc", 'password: "x y"', "x --db-secret=hunter2") == [
        "run api_key=[REDACTED]",
        "password: [REDACTED]",
        "x --db-secret=[REDACTED]",
    ]


def test_redact_strips_password_flag_values():
    [out] = redact_many("mysql --password hunter2 -u root")
    assert "hunter2" not in out, out
    assert out == "mysql --password [REDACTED] -u root"


def test_redact_strips_environment_assignments():
    assert redact_many("FOO=bar cmd", "export FOO=bar") == ["FOO=[REDACTED] cmd", "export FOO=[REDACTED]"]


def test_redact_strips_long_hex_runs():
    hex_run = "0123456789abcdef0123456789abcdef"
    short = "0123456789abcdef"
    assert redact_many(f"echo {hex_run}", f"echo {short}") == ["echo [REDACTED]", f"echo {short}"]


def test_redact_strips_long_mixed_case_base64_runs():
    run = "AbCdEf0123456789AbCdEf0123456789xyz"
    assert redact_many(f"echo {run}") == ["echo [REDACTED]"]


def test_redact_leaves_ordinary_commands_unchanged():
    commands = ["git status", "ls -la src", "cat src/lib/components/some/very/long/path/to/a/file/name-here.ts"]
    assert redact_many(*commands) == commands


# ---------------------------------------------------------------------------
# readJevConfig
# ---------------------------------------------------------------------------


def read_jev_configs(*envs):
    return jev_many("read", *([e] for e in envs))


def test_read_jev_config_null_when_off():
    assert read_jev_configs({}, {"GATE_JEV": ""}, {"GATE_JEV": "0"}) == [None, None, None]


def test_read_jev_config_defaults():
    config, prompt = JevConfig.read(BASE_ENV), JevPrompt.builtin_prompt("destructive")
    assert config == {
        "apiKey": "key-123",
        "url": JEV_URL,
        "model": "jev-latest",
        "allowThreshold": 0.95,
        "escalateThreshold": 0.5,
        "timeoutMs": 1500,
        "logPath": None,
        "scope": ["bash", "mcp"],
        "canLift": True,
        "prompt": prompt,
    }


def test_read_jev_config_scope_and_can_lift():
    scopes = ["", "bash", " MCP ", "mcp, bash,mcp"]
    lifts = ["", "1", "0"]
    results = read_jev_configs(
        *({**BASE_ENV, "GATE_JEV_SCOPE": v} for v in scopes),
        *({**BASE_ENV, "GATE_JEV_CAN_LIFT": v} for v in lifts),
    )
    assert [c["scope"] for c in results[: len(scopes)]] == [["bash", "mcp"], ["bash"], ["mcp"], ["bash", "mcp"]]
    assert [c["canLift"] for c in results[len(scopes) :]] == [True, True, False]
    for bad in [
        {"GATE_JEV_SCOPE": "bash,files"},
        {"GATE_JEV_SCOPE": ","},
        {"GATE_JEV_SCOPE": "none"},
        {"GATE_JEV_CAN_LIFT": "yes"},
        {"GATE_JEV_CAN_LIFT": "2"},
    ]:
        jev_config_error({**BASE_ENV, **bad})


def test_read_jev_config_empty_optional_vars_are_unset():
    [c] = read_jev_configs(
        {
            **BASE_ENV,
            "GATE_JEV_URL": "  ",
            "GATE_JEV_MODEL": "",
            "GATE_JEV_TIMEOUT_MS": "",
            "GATE_JEV_ALLOW_THRESHOLD": "",
            "GATE_JEV_ESCALATE_THRESHOLD": "",
            "GATE_JEV_LOG": "",
        }
    )
    assert c["url"] == JEV_URL
    assert c["model"] == "jev-latest"
    assert c["timeoutMs"] == 1500
    assert c["allowThreshold"] == 0.95
    assert c["escalateThreshold"] == 0.5
    assert c["logPath"] is None


def test_read_jev_config_overrides():
    [c] = read_jev_configs(
        {
            **BASE_ENV,
            "GATE_JEV_MODEL": "m",
            "GATE_JEV_TIMEOUT_MS": "30000",
            "GATE_JEV_ALLOW_THRESHOLD": "0.9",
            "GATE_JEV_ESCALATE_THRESHOLD": "1",
            "GATE_JEV_LOG": "/tmp/x.jsonl",
        }
    )
    assert c["model"] == "m"
    assert c["timeoutMs"] == 30000
    assert c["allowThreshold"] == 0.9
    assert c["escalateThreshold"] == 1
    assert c["logPath"] == "/tmp/x.jsonl"


@pytest.mark.parametrize(
    "env",
    [
        {"GATE_JEV": "yes", "TYPESAFE_API_KEY": "k"},
        {"GATE_JEV": "1"},
        {**BASE_ENV, "GATE_JEV_ALLOW_THRESHOLD": "1.5"},
        {**BASE_ENV, "GATE_JEV_ALLOW_THRESHOLD": "-0.1"},
        {**BASE_ENV, "GATE_JEV_ALLOW_THRESHOLD": "abc"},
        {**BASE_ENV, "GATE_JEV_ESCALATE_THRESHOLD": "2"},
        {**BASE_ENV, "GATE_JEV_ESCALATE_THRESHOLD": "abc"},
        {**BASE_ENV, "GATE_JEV_TIMEOUT_MS": "0"},
        {**BASE_ENV, "GATE_JEV_TIMEOUT_MS": "30001"},
        {**BASE_ENV, "GATE_JEV_TIMEOUT_MS": "1.5"},
        {**BASE_ENV, "GATE_JEV_TIMEOUT_MS": "abc"},
        {**BASE_ENV, "GATE_JEV_URL": "not a url"},
        {**BASE_ENV, "GATE_JEV_URL": "http://example.com"},
    ],
    ids=json.dumps,
)
def test_read_jev_config_rejects_invalid_input(env):
    jev_config_error(env)


def test_read_jev_config_accepts_loopback_http_urls():
    a, b = read_jev_configs(
        {**BASE_ENV, "GATE_JEV_URL": "http://127.0.0.1:1234"},
        {**BASE_ENV, "GATE_JEV_URL": "http://localhost"},
    )
    assert a["url"] == "http://127.0.0.1:1234"
    assert b["url"] == "http://localhost"


# ---------------------------------------------------------------------------
# jevDecision
# ---------------------------------------------------------------------------


def decide_many(*ps):
    return jev_many("jev_decision", *([p, CFG] for p in ps))


def test_jev_decision_passes_confident_read_only_and_unrelated():
    assert decide_many(probs(0.01, 0.97, 0.01, 0.01), probs(0.97, 0.01, 0.01, 0.01)) == [
        {"decision": "pass", "reason": "jev: read_only p=0.97 safe=0.98"},
        {"decision": "pass", "reason": "jev: unrelated p=0.97 safe=0.98"},
    ]


def test_jev_decision_sums_unrelated_and_read_only():
    assert decide_many(probs(0.6, 0.36, 0.02, 0.02)) == [
        {"decision": "pass", "reason": "jev: unrelated p=0.60 safe=0.96"}
    ]


def test_jev_decision_null_below_allow_threshold():
    assert decide_many(probs(0.04, 0.9, 0.04, 0.02), probs(0.4, 0.5, 0.05, 0.05)) == [None, None]


def test_jev_decision_asks_above_escalate_threshold():
    [d] = decide_many(probs(0.1, 0.35, 0.25, 0.3))
    assert d["decision"] == "ask"
    assert d["reason"] == "jev: destructive p=0.30 risk=0.55"


def test_jev_decision_no_ask_at_exactly_escalate_threshold():
    assert decide_many(probs(0.25, 0.25, 0.25, 0.25)) == [None]


def test_jev_decision_names_cloud_or_data_change_when_larger():
    [d] = decide_many(probs(0.05, 0.05, 0.6, 0.3))
    assert d["decision"] == "ask"
    assert d["reason"] == "jev: cloud_or_data_change p=0.60 risk=0.90"


# ---------------------------------------------------------------------------
# parseAnswer
# ---------------------------------------------------------------------------


def parse_many(*bodies):
    return jev_many("parse_answer", *([b, CFG["prompt"]] for b in bodies))


def test_parse_answer_accepts_well_formed_answer():
    p = probs(0.7, 0.1, 0.1, 0.1)
    assert parse_many(answer(p)) == [p]


def test_parse_answer_null_for_malformed_shapes():
    good = probs(0.7, 0.1, 0.1, 0.1)
    # JS `{ ...good, destructive: undefined }`: the key is dropped by JSON.
    without_destructive = {k: v for k, v in good.items() if k != "destructive"}
    bodies = [
        None,
        {},
        {"answers": {"cloud_change": {"type": "text", "probabilities": good}}},
        {"answers": {"cloud_change": {"type": "choice", "probabilities": "x"}}},
        answer(without_destructive),
        answer({**good, "destructive": "0.1"}),
        answer(probs(1.2, -0.1, 0, -0.1)),
        answer(probs(0.5, 0.1, 0.1, 0.1)),
    ]
    assert parse_many(*bodies) == [None] * len(bodies)


# ---------------------------------------------------------------------------
# buildState
# ---------------------------------------------------------------------------


def build_states(*calls):
    return jev_many("build_state", *([c] for c in calls))


def test_build_state_bash_payload_with_scripts_and_notes():
    """The state runJev sends for the JS 'sends the Bash payload' row (scripts given directly)."""
    [state] = build_states(
        bash_call(
            "bash infra/cloud/apply.sh --apply",
            [
                {"path": "infra/cloud/apply.sh", "content": "terraform apply\nTOKEN=abcdef\n"},
                {"path": "lib/.env.sh", "content": "ok\ncat .env\nfoo\n"},
            ],
        )
    )
    assert state["tool"] == "Bash"
    assert state["command"] == "bash infra/cloud/apply.sh --apply"
    assert state["scripts"] == [
        {"path": "infra/cloud/apply.sh", "content": "terraform apply\nTOKEN=[REDACTED]\n"},
        {"path": "lib/.env.sh", "content": "ok\n[line removed: .env reference]\nfoo\n"},
    ]
    assert state["notes"] == []


def test_build_state_caps_command_and_notes_cut():
    command = f"echo {'a ' * 6000}"
    [state] = build_states(bash_call(command))
    assert len(state["command"]) == 8000
    assert state["notes"] == [f"command cut to 8000 of {len(command)} characters"]


def test_build_state_caps_scripts_at_64_kb_total():
    def big(n):
        return {"path": f"f{n}.mjs", "content": "x" * 40000}

    [state] = build_states(
        bash_call(
            "node f1.mjs",
            [
                big(1),
                big(2),
                {**big(3), "content": "y"},
                {"path": "cut.mjs", "content": "z", "truncated": True, "size": 70000},
            ],
        )
    )
    assert [s["path"] for s in state["scripts"]] == ["f1.mjs", "f2.mjs"]
    assert sum(len(s["content"].encode()) for s in state["scripts"]) == 65536
    assert state["notes"] == [
        "cut.mjs cut at 64 KB",
        "scripts cut at 64 KB total: f2.mjs truncated; omitted: f3.mjs, cut.mjs",
    ]


def test_build_state_notes_file_cut_at_per_file_cap():
    [state] = build_states(
        bash_call("node a.mjs", [{"path": "a.mjs", "content": "x", "truncated": True, "size": 70000}])
    )
    assert state["notes"] == ["a.mjs cut at 64 KB"]
    assert len(state["scripts"]) == 1


# ---------------------------------------------------------------------------
# redactScript / redactMcpInput
# ---------------------------------------------------------------------------


SCRIPT_IN = [
    "#!/bin/bash",
    "source .env.local",
    "export API_TOKEN=abc123",
    'curl -H "Authorization: Bearer sekret" https://x',
    "echo ok",
]
SCRIPT_OUT = [
    "#!/bin/bash",
    "[line removed: .env reference]",
    "export API_TOKEN=[REDACTED]",
    'curl -H "Authorization: [REDACTED] [REDACTED]" https://x',
    "echo ok",
]


def test_redact_script_removes_env_lines_and_redacts_secrets():
    out, process_env = jev_many("redact_script", ["\n".join(SCRIPT_IN)], ["const a = process.env.FOO"])
    assert out == "\n".join(SCRIPT_OUT)
    assert "sekret" not in out
    # JS: process.env is not an .env file
    assert process_env == "const a = process.env.FOO"


def test_redact_mcp_input_redacts_sql_literals_keeps_statement_and_ids():
    [raw] = jev_many(
        "redact_mcp_input",
        [
            {
                "project_id": "abcdefghijklmnopqrst",
                "query": "INSERT INTO t (a, b) VALUES ('it''s secret', 5); UPDATE t SET x = 1 WHERE id=5",
            }
        ],
    )
    out = json.loads(raw)
    assert out["project_id"] == "abcdefghijklmnopqrst"
    assert out["query"] == "INSERT INTO t (a, b) VALUES ('[REDACTED]', 5); UPDATE t SET x = 1 WHERE id=5"


def test_redact_mcp_input_replaces_dollar_quoted_bodies():
    [raw] = jev_many(
        "redact_mcp_input",
        [{"sql": "CREATE FUNCTION f() RETURNS text AS $body$ select 'hunter2' $body$; SELECT $$x$$"}],
    )
    assert json.loads(raw)["sql"] == (
        "CREATE FUNCTION f() RETURNS text AS $body$[REDACTED]$body$; SELECT $$[REDACTED]$$"
    )


def test_redact_mcp_input_redacts_nested_secrets_bearer_and_env_mentions():
    [raw] = jev_many(
        "redact_mcp_input",
        [
            {
                "access_token": "tok-123",
                "nested": {
                    "headers": ["Authorization: Bearer abc.def", "X-Other: fine"],
                    "note": "line one\nsee .env.local for it\nline three",
                    "api_key": {"deep": "value"},
                },
                "count": 3,
            }
        ],
    )
    out = json.loads(raw)
    assert out["access_token"] == "[REDACTED]"
    assert out["nested"]["api_key"] == "[REDACTED]"
    assert out["nested"]["headers"] == ["Authorization: [REDACTED] [REDACTED]", "X-Other: fine"]
    assert out["nested"]["note"] == "line one\n[line removed: .env reference]\nline three"
    assert out["count"] == 3
    for secret in ["tok-123", "abc.def", "value"]:
        assert secret not in raw, secret


def test_redact_mcp_input_handles_empty_input():
    # JS `redactMcpInput(undefined)`: called with no argument (None here).
    assert jev_many("redact_mcp_input", [None], [{}]) == ["{}", "{}"]
