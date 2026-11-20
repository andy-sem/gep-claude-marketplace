"""Jev requests and the Jev layer (port of gate-jev.test.mjs, askJev / runJev part).

askJev and runJev run through hooks/gate.sh against the local Jev mock. What the JS tests read
from askJev's return value (error kind, latency, usage, probabilities) is read here from the
audit log (GATE_JEV_LOG). Rows already pinned by test_gate_hook_jev.py are not repeated here.
"""

import json
import time
from dataclasses import dataclass

import pytest

from testkit import DG, REPO
from testkit.hook import bash_input, decision, mcp_input, run_hook
from testkit.jev_mock import probs
from testkit.projects import temp_project

HERE = DG / "tests"
DOWN = "http://127.0.0.1:1/v1/systemone"
DBHOST_SQL = "mcp__plugin_dbhost_dbhost__execute_sql"
ISSUE_EDIT = "mcp__tracker__editIssue"

SAFE = probs(0, 1, 0, 0)
RISKY = probs(0, 0, 0, 1)
READ_ONLY = probs(0.01, 0.97, 0.01, 0.01)


def bash(command, cwd=HERE):
    return bash_input(command, cwd)


def mcp(tool, tool_input=None, cwd=REPO):
    return mcp_input(tool, tool_input or {}, cwd)


@dataclass
class JevRun:
    status: int
    stdout: str
    seconds: float
    hits: int
    bodies: list[dict]
    headers: list[dict]
    log: list[dict]


@pytest.fixture(scope="session")
def env_rules(tmp_path_factory):
    """One `env` rule asking on `cat .env` (a rule result for the .env row)."""
    path = tmp_path_factory.mktemp("rules") / "env.json"
    path.write_text(
        json.dumps(
            {
                "wrappers": [],
                "runners": [],
                "inertPrograms": [],
                "rules": [{"id": "env", "kind": "cli-gated", "programs": ["cat"], "gatedPrefixes": [[".env"]]}],
            }
        )
    )
    return path


@pytest.fixture
def base_env(tf_rules):
    return {"GATE_RULES": str(tf_rules), "CLAUDE_PROJECT_DIR": str(REPO)}


@pytest.fixture
def shipped(shipped_rules):
    return {"GATE_RULES": str(shipped_rules)}


@pytest.fixture
def run(impl, base_env):
    """Rules only (Jev off)."""
    return lambda stdin, env=None: run_hook(impl, stdin, base_env, env or {})


@pytest.fixture
def run_jev(impl, jev, base_env, tmp_path):
    """Run the hook with Jev on; the caller sets the mock answers. Requests and log lines are this run's only."""
    log_path = tmp_path / "audit.jsonl"

    def go(stdin, env=None, cwd=None):
        log_path.unlink(missing_ok=True)
        jev_env = {
            "GATE_JEV": "1",
            "TYPESAFE_API_KEY": "key-123",
            "GATE_JEV_URL": jev.url,
            "GATE_JEV_PROMPT": "cloud-change",
            "GATE_JEV_LOG": str(log_path),
            "GATE_JEV_TIMEOUT_MS": "5000",
        }
        before = jev.hits
        started = time.monotonic()
        r = run_hook(impl, stdin, base_env, jev_env, env or {}, cwd=cwd)
        seconds = time.monotonic() - started
        log = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []
        return JevRun(
            r.status,
            r.stdout,
            seconds,
            jev.hits - before,
            [b for b in jev.bodies[before:] if b is not None],
            jev.headers[before:],
            log,
        )

    return go


def reason(stdout):
    return decision(stdout)["permissionDecisionReason"]


# ---------------------------------------------------------------------------
# askJev
# ---------------------------------------------------------------------------


def test_request_shape(jev, run_jev):
    """askJev returns probabilities, usage and latency and sends a well-formed request."""
    p = READ_ONLY
    jev.answer(p, usage={"input_tokens": 900, "output_tokens": 12})
    r = run_jev(bash("git status"))
    [record] = r.log
    assert record["probabilities"] == p
    assert record["usage"] == {"input_tokens": 900, "output_tokens": 12}
    assert isinstance(record["latencyMs"], (int, float))
    assert r.hits == 1  # one POST to GATE_JEV_URL (the mock serves POST only)
    assert r.headers[0]["authorization"] == "Bearer key-123"
    body = r.bodies[0]
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
    # examples cover Bash, scripts, Terraform, workflows, generic MCP calls, and unrelated calls
    examples = "\n".join(e for o in q["criteria"].values() for e in o["examples"])
    for needle in [
        "kubectl apply",
        "bash infra/apply.sh",
        "node scripts/provision-dev.mjs",
        "terraform plan",
        "terraform apply",
        "terraform destroy",
        "terraform test, where every test file",
        "terraform test, where a test file",
        "gh workflow run",
        "runs SQL: SELECT",
        "runs SQL: INSERT",
        "runs SQL: DROP",
        "applies a database migration",
        "deploys a service",
        "git push --force",
        "edits the title of an issue",
        "clicks in a browser",
    ]:
        assert needle in examples, needle
    assert "local_write" not in json.dumps(body)


def test_error_has_latency(jev, run_jev):
    jev.answer(status=500)
    [record] = run_jev(bash("ls")).log
    assert record["outcome"] == "fallback: http 500"
    assert isinstance(record["latencyMs"], (int, float))


def test_usage_null_when_absent(jev, run_jev):
    jev.answer(kind="raw", body={"answers": {"cloud_change": {"type": "choice", "probabilities": READ_ONLY}}})
    [record] = run_jev(bash("ls")).log
    assert record["probabilities"] == READ_ONLY
    assert record["usage"] is None


def test_non_retryable_http_error(jev, run_jev):
    jev.answer(status=401)
    r = run_jev(bash("ls"))
    assert r.log[0]["outcome"] == "fallback: http 401"
    assert r.hits == 1


def test_retries_429_then_succeeds(jev, run_jev):
    p = probs(0.97, 0.01, 0.01, 0.01)
    jev.sequence({"status": 429, "retry_after": "0"}, {"probs": p})
    r = run_jev(bash("terraform apply"))
    assert r.hits == 2
    assert r.log[0]["probabilities"] == p
    assert r.log[0]["decision"] == "pass"
    assert r.stdout == ""  # the ok answer lifts the tf rule ask


def test_retry_after_over_budget_gives_up(jev, run_jev):
    jev.answer(status=529, retry_after="10")
    r = run_jev(bash("ls"), {"GATE_JEV_TIMEOUT_MS": "200"})
    assert r.log[0]["outcome"] == "fallback: http 529"
    assert r.hits == 1


def test_hang_times_out(jev, run_jev):
    jev.answer(kind="hang")
    r = run_jev(bash("ls"), {"GATE_JEV_TIMEOUT_MS": "50"})
    assert r.log[0]["outcome"] == "fallback: timeout"
    assert r.seconds < 5, r.seconds


def test_network_failure(run_jev):
    r = run_jev(bash("ls"), {"GATE_JEV_URL": DOWN})
    assert r.log[0]["outcome"] == "fallback: network"


def test_malformed_bodies(jev, run_jev):
    jev.answer(kind="malformed")
    assert run_jev(bash("ls")).log[0]["outcome"] == "fallback: malformed"
    jev.answer(kind="raw", body={"answers": {}})
    assert run_jev(bash("ls")).log[0]["outcome"] == "fallback: malformed"


# ---------------------------------------------------------------------------
# runJev
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "env"),
    [({"status": 500}, {}), ({}, {"GATE_JEV_URL": DOWN})],
    ids=["http-500", "network"],
)
def test_failures_keep_rule_result_for_bash_and_mcp(jev, run, run_jev, shipped, answer, env):
    """Failure modes test_jev_failures_give_rule_result does not cover (500, network)."""
    jev.answer(SAFE, **answer)
    for stdin, rule_reason in [
        (bash("terraform apply"), "terraform:"),
        (mcp(DBHOST_SQL, {"query": "SELECT 1"}), "dbhost-mcp:"),
    ]:
        r = run_jev(stdin, {**shipped, **env})
        assert reason(r.stdout).startswith(rule_reason), stdin
        assert r.stdout == run(stdin, shipped).stdout
        assert r.log[0]["outcome"].startswith("fallback: ")
    for stdin in [bash("git status"), mcp(ISSUE_EDIT, {"issueIdOrKey": "PROJ-1"})]:
        r = run_jev(stdin, {**shipped, **env})
        assert r.stdout == "", stdin
        assert r.log[0]["outcome"].startswith("fallback: ")


def test_can_lift_0_mcp(jev, run_jev, shipped):
    """The MCP half of the canLift row (the Bash half is test_can_lift_0_keeps_rule_asks_jev_still_adds)."""
    no_lift = {**shipped, "GATE_JEV_CAN_LIFT": "0"}
    rule_call = mcp(DBHOST_SQL, {"a": 1})
    no_rule_call = mcp(ISSUE_EDIT, {"a": 1})
    jev.answer(SAFE)
    assert reason(run_jev(rule_call, no_lift).stdout).startswith("dbhost-mcp:")
    assert run_jev(no_rule_call, no_lift).stdout == ""
    assert run_jev(rule_call, shipped).stdout == ""
    jev.answer(RISKY)
    added = decision(run_jev(no_rule_call, no_lift).stdout)
    assert added["permissionDecision"] == "ask"
    assert added["permissionDecisionReason"].startswith("jev: ")


def test_env_reference_never_sent(jev, run, run_jev, env_rules):
    rules = {"GATE_RULES": str(env_rules)}
    alone = run(bash("cat .env"), rules)
    assert reason(alone.stdout).startswith("env:")
    jev.answer(SAFE)
    r = run_jev(bash("cat .env"), rules)
    assert r.hits == 0
    assert r.stdout == alone.stdout


def test_no_rule_opinion_asks_for_bash_and_mcp(jev, run, run_jev):
    jev.answer(probs(0, 0.05, 0.05, 0.9))
    for stdin in [bash("rm -rf x"), mcp("mcp__x__y")]:
        assert run(stdin).stdout == "", stdin  # the rules have no opinion
        o = decision(run_jev(stdin).stdout)
        assert o["permissionDecision"] == "ask"
        assert o["permissionDecisionReason"] == "jev: destructive p=0.90 risk=0.95"


def test_undecided_keeps_rule_result(jev, run, run_jev):
    jev.answer(probs(0.04, 0.9, 0.04, 0.02))
    alone = run(bash("terraform apply"))
    assert reason(alone.stdout).startswith("tf:")
    r = run_jev(bash("terraform apply"))
    assert r.hits == 1
    assert r.stdout == alone.stdout


def test_bash_payload_exact_scripts_and_no_notes(jev, run_jev, shipped, tmp_path):
    """Adds the exact `scripts` and empty `notes` that test_script_request_carries_redacted_script leaves out."""
    root = temp_project(tmp_path, {"infra/cloud/apply.sh": "terraform apply\nTOKEN=abcdef\n"})
    jev.answer(READ_ONLY)
    state = run_jev(bash("bash infra/cloud/apply.sh --apply", root), shipped).bodies[0]["state"]
    assert state["tool"] == "Bash"
    assert state["command"] == "bash infra/cloud/apply.sh --apply"
    assert state["scripts"] == [{"path": "infra/cloud/apply.sh", "content": "terraform apply\nTOKEN=[REDACTED]\n"}]
    assert state["notes"] == []


def test_mcp_payload_input_and_cut_note(jev, run_jev):
    """Adds the exact input, no `command`, and the cut note to test_mcp_calls_send_tool_name_and_redacted_input."""
    jev.answer(READ_ONLY)
    state = run_jev(mcp(DBHOST_SQL, {"query": "SELECT 1"})).bodies[0]["state"]
    assert state["tool"] == DBHOST_SQL
    assert state["input"] == '{"query":"SELECT 1"}'
    assert state["notes"] == []
    assert "command" not in state
    text = {"text": "lorem ipsum " * 750}
    state = run_jev(mcp("mcp__x__y", text)).bodies[0]["state"]
    assert len(state["input"]) == 8000
    full = len(json.dumps(text, separators=(",", ":")))
    assert state["notes"] == [f"input cut to 8000 of {full} characters"]


# ---------------------------------------------------------------------------
# audit log
# ---------------------------------------------------------------------------


def test_audit_log_redacted_records(jev, impl, base_env, shipped, tmp_path):
    """Bash pass with a script, skipped .env, MCP pass over a rule, and a fallback, in one log."""
    log = tmp_path / "audit.jsonl"
    root = temp_project(tmp_path, {"a.mjs": "x"})
    env = {
        **shipped,
        "GATE_JEV": "1",
        "TYPESAFE_API_KEY": "key-123",
        "GATE_JEV_URL": jev.url,
        "GATE_JEV_PROMPT": "cloud-change",
        "GATE_JEV_LOG": str(log),
    }

    def go(stdin):
        return run_hook(impl, stdin, base_env, env)

    jev.answer(probs(0.01, 0.98, 0.005, 0.005), usage={"input_tokens": 1000})
    go(bash("TOPSECRET_X=supersecret123 node a.mjs", root))
    go(bash("cat .env"))
    go(mcp(DBHOST_SQL, {"password": "supersecret123", "q": 1}))
    jev.answer(status=401)
    go(bash("terraform apply"))
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
    assert isinstance(lines[0]["latencyMs"], (int, float))
    assert lines[0]["probabilities"]["read_only"] == 0.98
    assert lines[0]["ts"]
    assert lines[1]["command"] is None
    assert lines[1]["outcome"].startswith("skipped")
    assert isinstance(lines[1]["latencyMs"], (int, float))
    assert lines[2]["tool"] == DBHOST_SQL
    assert lines[2]["input"] == '{"password":"[REDACTED]","q":1}'
    assert lines[2]["rule"].startswith("dbhost-mcp:")
    assert lines[2]["decision"] == "pass"
    assert lines[3]["outcome"] == "fallback: http 401"
    assert lines[3]["rule"].startswith("terraform:")
    assert isinstance(lines[3]["latencyMs"], (int, float))
