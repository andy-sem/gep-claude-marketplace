"""Jev pure helpers (port of gate-jev.test.mjs, pure part).

Runs in-process against the jev package (decisions: test_jev_judge.py). askJev / runJev rows are in test_jev_http.py
(through the hook) and test_jev_request_py.py (in-process).
"""

import json

import pytest

from destructive_guard.errors import JevConfigError
from destructive_guard.jev.config import JevConfig
from destructive_guard.jev.prompt import JevPrompt
from destructive_guard.jev.redactor import Redactor
from destructive_guard.jev.request import JevRequest
from testkit.jev_mock import JevMock

BASE_ENV = {"TYPESAFE_API_KEY": "key-123"}
JEV_URL = "https://api.typesafe.ai/v1/systemone"
# The JS `cfg` without `logPath`; the ported tests exercise the cloud-change preset.
CFG = {
    "apiKey": "key-123",
    "url": "https://example.test/v1",
    "model": "jev-latest",
    "timeoutMs": 500,
    "escalateThreshold": 0.5,
    "prompt": JevPrompt.builtin_prompt("cloud-change"),
}


def jev_many(fn, *arg_lists):
    owner = JevConfig if fn in ("read",) else Redactor if fn.startswith("redact") else JevRequest if fn in ("parse_answer", "build_state") else None
    return [getattr(owner, fn)(*args) for args in arg_lists]


def answer(p):
    return {"answers": {"cloud_change": {"type": "choice", "probabilities": p}}}


def bash_call(command):
    return {"tool": "Bash", "command": command}


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


def test_read_jev_config_has_no_off_state():
    with pytest.raises(JevConfigError) as e:
        JevConfig.read({})
    assert e.value.kind == "noKey"
    with pytest.raises(JevConfigError):
        JevConfig.read({"TYPESAFE_API_KEY": "  "})


def test_read_jev_config_defaults():
    config, prompt = JevConfig.read(BASE_ENV), JevPrompt.builtin_prompt("destructive")
    assert config == {
        "apiKey": "key-123",
        "url": JEV_URL,
        "model": "jev-latest",
        "escalateThreshold": 0.5,
        "timeoutMs": 1500,
        "prompt": prompt,
    }


def test_read_jev_config_empty_optional_vars_are_unset():
    [c] = read_jev_configs(
        {**BASE_ENV, "GATE_JEV_URL": "  ", "GATE_JEV_MODEL": "", "GATE_JEV_TIMEOUT_MS": "", "GATE_JEV_ESCALATE_THRESHOLD": ""}
    )
    assert c["url"] == JEV_URL
    assert c["model"] == "jev-latest"
    assert c["timeoutMs"] == 1500
    assert c["escalateThreshold"] == 0.5


def test_read_jev_config_overrides():
    [c] = read_jev_configs(
        {**BASE_ENV, "GATE_JEV_MODEL": "m", "GATE_JEV_TIMEOUT_MS": "30000", "GATE_JEV_ESCALATE_THRESHOLD": "1"}
    )
    assert (c["model"], c["timeoutMs"], c["escalateThreshold"]) == ("m", 30000, 1)


@pytest.mark.parametrize(
    ("env", "kind"),
    [
        ({}, "noKey"),
        ({**BASE_ENV, "GATE_JEV_ESCALATE_THRESHOLD": "2"}, "badValue"),
        ({**BASE_ENV, "GATE_JEV_ESCALATE_THRESHOLD": "abc"}, "badValue"),
        ({**BASE_ENV, "GATE_JEV_TIMEOUT_MS": "0"}, "badValue"),
        ({**BASE_ENV, "GATE_JEV_TIMEOUT_MS": "30001"}, "badValue"),
        ({**BASE_ENV, "GATE_JEV_TIMEOUT_MS": "1.5"}, "badValue"),
        ({**BASE_ENV, "GATE_JEV_TIMEOUT_MS": "abc"}, "badValue"),
        ({**BASE_ENV, "GATE_JEV_URL": "not a url"}, "badUrl"),
        ({**BASE_ENV, "GATE_JEV_URL": "http://example.com"}, "badUrl"),
        ({**BASE_ENV, "GATE_JEV_PROMPT": "nope"}, "badPrompt"),
        ({**BASE_ENV, "GATE_JEV_PROMPT": "/no/such/prompt.json"}, "badPrompt"),
    ],
    ids=lambda v: json.dumps(v) if isinstance(v, dict) else v,
)
def test_read_jev_config_rejects_invalid_input(env, kind):
    with pytest.raises(JevConfigError) as e:
        JevConfig.read(env)
    assert e.value.kind == kind


def test_read_jev_config_accepts_loopback_http_urls():
    a, b = read_jev_configs(
        {**BASE_ENV, "GATE_JEV_URL": "http://127.0.0.1:1234"},
        {**BASE_ENV, "GATE_JEV_URL": "http://localhost"},
    )
    assert a["url"] == "http://127.0.0.1:1234"
    assert b["url"] == "http://localhost"


# ---------------------------------------------------------------------------
# parseAnswer
# ---------------------------------------------------------------------------


def parse_many(*bodies):
    return jev_many("parse_answer", *([b, CFG["prompt"]] for b in bodies))


def test_parse_answer_accepts_well_formed_answer():
    p = JevMock.probs(0.7, 0.1, 0.1, 0.1)
    assert parse_many(answer(p)) == [p]


def test_parse_answer_null_for_malformed_shapes():
    good = JevMock.probs(0.7, 0.1, 0.1, 0.1)
    # JS `{ ...good, destructive: undefined }`: the key is dropped by JSON.
    without_destructive = {k: v for k, v in good.items() if k != "destructive"}
    bodies = [
        None,
        {},
        {"answers": {"cloud_change": {"type": "text", "probabilities": good}}},
        {"answers": {"cloud_change": {"type": "choice", "probabilities": "x"}}},
        answer(without_destructive),
        answer({**good, "destructive": "0.1"}),
        answer(JevMock.probs(1.2, -0.1, 0, -0.1)),
        answer(JevMock.probs(0.5, 0.1, 0.1, 0.1)),
    ]
    assert parse_many(*bodies) == [None] * len(bodies)


# ---------------------------------------------------------------------------
# buildState
# ---------------------------------------------------------------------------


def build_states(*calls):
    return jev_many("build_state", *([c] for c in calls))


def test_build_state_bash_payload_is_the_redacted_command_only():
    [state] = build_states(bash_call("bash infra/cloud/apply.sh --apply TOKEN=abcdef"))
    assert state == {
        "tool": "Bash",
        "command": "bash infra/cloud/apply.sh --apply TOKEN=[REDACTED]",
        "notes": [],
    }


def test_build_state_skips_env_references():
    assert build_states(bash_call("cat .env"), {"tool": "mcp__x__y", "input": {"p": "a/.env.local"}}) == [None, None]


def test_build_state_caps_command_and_notes_cut():
    command = f"echo {'a ' * 6000}"
    [state] = build_states(bash_call(command))
    assert len(state["command"]) == 8000
    assert state["notes"] == [f"command cut to 8000 of {len(command)} characters"]


# ---------------------------------------------------------------------------
# redactScript / redactMcpInput
# ---------------------------------------------------------------------------


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
