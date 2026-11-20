"""Contract: hooks/gate.sh with Jev against a local mock (port of gate-hook.test.mjs, Jev part)."""

import json
import re
from dataclasses import dataclass

import pytest

from testkit import DG, REPO
from testkit.hook import bash_input, decision, mcp_input, run_hook
from testkit.jev_mock import probs
from testkit.projects import provision_project, temp_project

HERE = DG / "tests"
DOWN = "http://127.0.0.1:1/v1/systemone"

DBHOST_SQL = "mcp__plugin_dbhost_dbhost__execute_sql"
CLOUDCTL_MCP = "mcp__cloudctl__run_cloudctl_command"
ISSUE_EDIT = "mcp__tracker__editIssue"
BROWSER_CLICK = "mcp__browser__click"

UNRELATED = probs(0.97, 0.01, 0.01, 0.01)
READ_ONLY = probs(0.01, 0.97, 0.01, 0.01)
RISKY = probs(0.1, 0.1, 0.6, 0.2)
DYNAMIC_RUN = 'run(){ "$@" > log 2>&1; }; run format pnpm format:check'


def bash(command, cwd=HERE):
    return bash_input(command, cwd)


def mcp(tool, tool_input=None, cwd=REPO):
    return mcp_input(tool, tool_input or {}, cwd)


@dataclass
class JevRun:
    status: int
    stdout: str
    hits: int
    bodies: list[dict]


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
def run_jev(impl, jev, base_env):
    """`answer` is a probabilities dict, or {"kind": "status"|"hang"|"malformed", ...}."""

    def go(stdin, answer, env=None, cwd=None):
        if "kind" in answer:
            jev.answer(kind=answer["kind"], status=answer.get("status"))
        else:
            jev.answer(answer)
        jev_env = {
            "GATE_JEV": "1",
            "GATE_JEV_LOG": "",
            "TYPESAFE_API_KEY": "test-key",
            "GATE_JEV_URL": jev.url,
            "GATE_JEV_TIMEOUT_MS": "5000",
            "GATE_JEV_PROMPT": "cloud-change",
        }
        r = run_hook(impl, stdin, base_env, jev_env, env or {}, cwd=cwd)
        bodies = list(jev.bodies)
        return JevRun(r.status, r.stdout, len(bodies), [b for b in bodies if b is not None])

    return go


def reason(stdout):
    return decision(stdout)["permissionDecisionReason"]


def test_jev_unset_gives_rules_only_output(run, run_jev):
    for command in ["terraform apply", "git status"]:
        r = run_jev(bash(command), probs(0.01, 0.97, 0.01, 0.01), {"GATE_JEV": ""})
        assert r.status == 0
        assert r.stdout == run(bash(command)).stdout
        assert r.hits == 0


def test_rule_matched_read_only_097_passes(run_jev):
    r = run_jev(bash("terraform apply"), probs(0.01, 0.97, 0.01, 0.01))
    assert r.status == 0
    assert r.stdout == ""
    assert r.hits == 1


def test_in_scope_no_rule_risk_055_asks(run_jev):
    r = run_jev(bash("terraform plan"), probs(0.15, 0.3, 0.25, 0.3))
    assert r.status == 0
    o = decision(r.stdout)
    assert o["permissionDecision"] == "ask"
    assert o["permissionDecisionReason"] == "jev: destructive p=0.30 risk=0.55"
    assert r.hits == 1


def test_command_outside_rule_programs_goes_to_jev(run_jev):
    for command in ["git status", "node x.mjs", "rm -rf build"]:
        r = run_jev(bash(command), probs(0.1, 0.1, 0.6, 0.2))
        o = decision(r.stdout)
        assert o["permissionDecision"] == "ask", command
        assert o["permissionDecisionReason"].startswith("jev: "), command
        assert r.hits == 1, command


def test_read_only_090_rule_result_stands(run_jev):
    gated = run_jev(bash("terraform apply"), probs(0.04, 0.9, 0.03, 0.03))
    assert reason(gated.stdout).startswith("tf:")
    passed = run_jev(bash("terraform plan"), probs(0.04, 0.9, 0.03, 0.03))
    assert passed.stdout == ""


def test_unparsable_read_only_097_passes(run_jev):
    for command in [DYNAMIC_RUN, "echo 'open", 'eval "$CMD"']:
        r = run_jev(bash(command), probs(0.01, 0.97, 0.01, 0.01))
        assert r.status == 0
        assert r.stdout == "", command
        assert r.hits == 1, command


def test_unparsable_risky_asks_jev(run_jev):
    r = run_jev(bash(DYNAMIC_RUN), probs(0.1, 0.2, 0.6, 0.1))
    o = decision(r.stdout)
    assert o["permissionDecision"] == "ask"
    assert o["permissionDecisionReason"].startswith("jev: cloud_or_data_change")
    assert r.hits == 1


def test_unsure_or_unreachable_unparsable_asks_strict(run_jev):
    unsure = run_jev(bash(DYNAMIC_RUN), probs(0.04, 0.9, 0.03, 0.03), {"GATE_STRICT": "1"})
    assert reason(unsure.stdout) == "unparsable: dynamic command word"
    down = run_jev(bash(DYNAMIC_RUN), probs(0.01, 0.97, 0.01, 0.01), {"GATE_JEV_URL": DOWN, "GATE_STRICT": "1"})
    assert reason(down.stdout) == "unparsable: dynamic command word"


def test_unparsable_without_jev_asks_strict(run_jev):
    r = run_jev(bash(DYNAMIC_RUN), probs(0.01, 0.97, 0.01, 0.01), {"GATE_JEV": "", "GATE_STRICT": "1"})
    assert reason(r.stdout) == "unparsable: dynamic command word"
    assert r.hits == 0


def test_unparsable_default_no_opinion(run_jev):
    off = run_jev(bash(DYNAMIC_RUN), probs(0.01, 0.97, 0.01, 0.01), {"GATE_JEV": ""})
    assert off.stdout == ""
    assert off.hits == 0
    # with Jev on, Jev still judges it; unsure falls back to no opinion
    unsure = run_jev(bash(DYNAMIC_RUN), probs(0.04, 0.9, 0.03, 0.03))
    assert unsure.stdout == ""
    assert unsure.hits == 1
    risky = run_jev(bash(DYNAMIC_RUN), probs(0.1, 0.2, 0.6, 0.1))
    assert reason(risky.stdout).startswith("jev: ")


def test_input_level_unparsable_and_gate_config_still_ask(run_jev, bad_rules):
    lifted = probs(0.01, 0.97, 0.01, 0.01)
    no_command = run_jev(json.dumps({"tool_name": "Bash", "tool_input": {}}), lifted)
    assert reason(no_command.stdout).startswith("unparsable:")
    bad_json = run_jev("not json", lifted)
    assert reason(bad_json.stdout).startswith("unparsable:")
    bad = run_jev(bash("git status"), lifted, {"GATE_RULES": str(bad_rules)})
    assert reason(bad.stdout).startswith("gate-config")
    assert no_command.hits + bad_json.hits + bad.hits == 0


def test_missing_api_key_asks_gate_config(run_jev):
    r = run_jev(bash("git status"), probs(0.01, 0.97, 0.01, 0.01), {"TYPESAFE_API_KEY": ""})
    assert r.status == 0
    o = decision(r.stdout)
    assert o["permissionDecision"] == "ask"
    assert re.match(r"^gate-config: .*TYPESAFE_API_KEY", o["permissionDecisionReason"])
    assert r.hits == 0


def test_unreachable_service_rule_result_stands(run_jev):
    r = run_jev(bash("terraform apply"), probs(0.01, 0.97, 0.01, 0.01), {"GATE_JEV_URL": DOWN})
    assert reason(r.stdout).startswith("tf:")


# --- Jev on every Bash and MCP call, against the shipped rules ---------------


def test_every_bash_and_mcp_call_one_request_file_tools_none(run_jev, shipped):
    for stdin in [
        bash("git status"),
        mcp(DBHOST_SQL, {"query": "SELECT 1"}),
        mcp(CLOUDCTL_MCP, {"args": ["run", "services", "list"]}),
        mcp(ISSUE_EDIT, {"issueIdOrKey": "PROJ-1"}),
        mcp(BROWSER_CLICK, {"action": "left_click"}),
    ]:
        r = run_jev(stdin, UNRELATED, shipped)
        assert r.hits == 1, stdin
        assert r.status == 0
    for stdin in [
        mcp("Read", {"file_path": "/x"}),
        mcp("Edit", {"file_path": "/x", "old_string": "a", "new_string": "b"}),
        mcp("Write", {"file_path": "/x", "content": "y"}),
        mcp("Glob", {"pattern": "*"}),
        mcp("Grep", {"pattern": "x"}),
    ]:
        r = run_jev(stdin, RISKY, shipped)
        assert r.hits == 0, stdin
        assert r.stdout == "", stdin


def test_risk_above_05_asks_when_no_rule_matched(run_jev, shipped):
    for stdin in [bash("git status"), bash("node x.mjs"), mcp(ISSUE_EDIT, {"issueIdOrKey": "PROJ-1"})]:
        o = decision(run_jev(stdin, RISKY, shipped).stdout)
        assert o["permissionDecision"] == "ask", stdin
        assert o["permissionDecisionReason"].startswith("jev: cloud_or_data_change")


def test_unrelated_097_gives_no_output(run_jev, shipped):
    for stdin in [
        bash("git push --force"),
        bash("wrangler deploy"),
        mcp(ISSUE_EDIT, {"issueIdOrKey": "PROJ-1", "fields": {"summary": "x"}}),
    ]:
        r = run_jev(stdin, UNRELATED, shipped)
        assert r.stdout == "", stdin
        assert r.hits == 1


def test_read_only_097_lifts_rule_and_script_asks(run, run_jev, shipped, tmp_path):
    root = temp_project(tmp_path, {"plan.sh": "terraform plan -out x\n"})
    cases = [
        (bash("cloudctl sql instances describe $P"), "cloudctl:"),
        (mcp(DBHOST_SQL, {"query": "SELECT 1"}), "dbhost-mcp:"),
        (bash("bash plan.sh", root), "script:"),
    ]
    for stdin, rule_reason in cases:
        alone = run(stdin, shipped)
        assert reason(alone.stdout).startswith(rule_reason), stdin
        r = run_jev(stdin, READ_ONLY, shipped)
        assert r.stdout == "", stdin
        assert r.hits == 1


def test_scope_limits_which_calls_are_sent(run, run_jev, shipped):
    bash_in = bash("git push --force")
    mcp_in = mcp(ISSUE_EDIT, {"issueIdOrKey": "PROJ-1"})

    def rules_only(stdin):
        return run(stdin, shipped).stdout

    # bash only: MCP calls keep the rule result and make no request.
    r = run_jev(mcp_in, RISKY, {**shipped, "GATE_JEV_SCOPE": "bash"})
    assert r.hits == 0
    assert r.stdout == rules_only(mcp_in)
    r = run_jev(bash_in, UNRELATED, {**shipped, "GATE_JEV_SCOPE": "bash"})
    assert r.hits == 1
    assert r.stdout == ""
    # mcp only: Bash calls keep the rule result and make no request.
    r = run_jev(bash_in, UNRELATED, {**shipped, "GATE_JEV_SCOPE": "mcp"})
    assert r.hits == 0
    assert r.stdout == rules_only(bash_in)
    r = run_jev(mcp_in, RISKY, {**shipped, "GATE_JEV_SCOPE": "mcp"})
    assert r.hits == 1
    assert decision(r.stdout)["permissionDecision"] == "ask"


def test_can_lift_0_keeps_rule_asks_jev_still_adds(run_jev, shipped):
    no_lift = {**shipped, "GATE_JEV_CAN_LIFT": "0"}
    r = run_jev(bash("cloudctl sql instances describe $P"), READ_ONLY, no_lift)
    assert r.hits == 1
    assert reason(r.stdout).startswith("cloudctl:")
    added = run_jev(bash("git status"), RISKY, no_lift)
    assert reason(added.stdout).startswith("jev: ")
    quiet = run_jev(bash("git status"), READ_ONLY, no_lift)
    assert quiet.stdout == ""


def test_invalid_scope_or_can_lift_asks_gate_config(run_jev, shipped):
    for env in [{"GATE_JEV_SCOPE": "files"}, {"GATE_JEV_CAN_LIFT": "no"}]:
        r = run_jev(bash("git status"), READ_ONLY, {**shipped, **env})
        assert r.hits == 0
        o = decision(r.stdout)
        assert o["permissionDecision"] == "ask"
        assert o["permissionDecisionReason"].startswith("gate-config: GATE_JEV_")


def test_script_request_carries_redacted_script(run_jev, shipped, tmp_path):
    root = temp_project(
        tmp_path,
        {
            "infra/cloud/apply.sh": "#!/bin/bash\n"
            "export API_TOKEN=hunter2hunter2\n"
            "source .env.local\n"
            "terraform -chdir=environments/dev apply dev.tfplan\n"
        },
    )
    r = run_jev(bash("bash infra/cloud/apply.sh --apply", root), probs(0.05, 0.05, 0.9, 0), shipped)
    o = decision(r.stdout)
    assert o["permissionDecision"] == "ask"
    assert o["permissionDecisionReason"].startswith("jev: cloud_or_data_change")
    state = r.bodies[0]["state"]
    assert state["command"] == "bash infra/cloud/apply.sh --apply"
    assert len(state["scripts"]) == 1
    content = state["scripts"][0]["content"]
    assert state["scripts"][0]["path"] == "infra/cloud/apply.sh"
    assert "hunter2" not in content
    assert "API_TOKEN=[REDACTED]" in content
    assert ".env.local" not in content
    assert "[line removed: .env reference]" in content
    assert "terraform -chdir" in content


def test_terraform_test_sends_test_files_and_jev_can_lift(run_jev, shipped, tmp_path):
    root = temp_project(
        tmp_path,
        {
            "infra/env/main.tf": 'provider "acmecloud" {}\n',
            "infra/env/tests/iam.tftest.hcl": 'mock_provider "acmecloud" {}\n\nrun "grants" {\n  command = apply\n}\n',
        },
    )
    command = "cd infra/env && terraform test"
    unsure = run_jev(bash(command, root), probs(0.66, 0.2, 0.14, 0), shipped)
    assert reason(unsure.stdout).startswith("terraform: gated invocation")
    state = unsure.bodies[0]["state"]
    assert [s["path"] for s in state["scripts"]] == ["infra/env/tests/iam.tftest.hcl"]
    assert 'mock_provider "acmecloud"' in state["scripts"][0]["content"]
    sure = run_jev(bash(command, root), probs(0.1, 0.88, 0.02, 0), shipped)
    assert sure.stdout.strip() == ""


def test_unreadable_files_reach_jev_as_notes(run_jev, shipped, tmp_path):
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    (outside / "deploy.sh").write_text("echo hi\n")
    files = {"scripts/many.mjs": "".join(f'import "./f{k}.mjs"\n' for k in range(40))}
    files.update({f"scripts/f{k}.mjs": "export {}\n" for k in range(40)})
    root = temp_project(tmp_path, files)
    r = run_jev(bash(f"bash {outside / 'deploy.sh'}", root), RISKY, shipped)
    state = r.bodies[0]["state"]
    assert state["scripts"] == []
    assert len(state["notes"]) == 1, state["notes"]
    assert re.search(r"not read: is outside the project$", state["notes"][0])
    capped = run_jev(bash("node scripts/many.mjs", root), RISKY, shipped)
    notes = capped.bodies[0]["state"]["notes"]
    assert any(re.search(r"not read: more than 32 files$", n) for n in notes), notes


def test_imports_followed_to_depth_3_with_caps(run_jev, shipped, tmp_path):
    filler = "lorem ipsum " * 6000
    root = temp_project(
        tmp_path,
        {
            "scripts/provision.mjs": 'import "./chain1.mjs"\nimport "./big.mjs"\nimport "./other.mjs"\n',
            "scripts/chain1.mjs": 'import "./chain2.mjs"\n',
            "scripts/chain2.mjs": 'import "./chain3.mjs"\n',
            "scripts/chain3.mjs": 'import "./chain4.mjs"\n',
            "scripts/chain4.mjs": "export {}\n",
            "scripts/big.mjs": f"// {filler}\n",
            "scripts/other.mjs": "export {}\n",
        },
    )
    r = run_jev(bash("node scripts/provision.mjs", root), RISKY, shipped)
    state = r.bodies[0]["state"]
    order = [
        "scripts/provision.mjs",
        "scripts/chain1.mjs",
        "scripts/big.mjs",
        "scripts/other.mjs",
        "scripts/chain2.mjs",
        "scripts/chain3.mjs",
    ]
    assert [s["path"] for s in state["scripts"]] == order[: len(state["scripts"])]
    assert not any("chain4" in s["path"] for s in state["scripts"])
    assert "scripts/big.mjs cut at 64 KB" in state["notes"]
    assert any(re.match(r"^scripts cut at 64 KB total: ", n) for n in state["notes"])
    total = sum(len(s["content"].encode()) for s in state["scripts"])
    assert total <= 65536, total


def test_provision_script_sent_with_imports(run_jev, shipped, tmp_path):
    r = run_jev(bash("node scripts/provision-cloud-app-dev.mjs", provision_project(tmp_path)), RISKY, shipped)
    paths = [s["path"] for s in r.bodies[0]["state"]["scripts"]]
    assert paths[0] == "scripts/provision-cloud-app-dev.mjs"
    assert "scripts/deploy-cloud-app-dev.mjs" in paths, paths


def test_mcp_calls_send_tool_name_and_redacted_input(run_jev, shipped):
    r = run_jev(
        mcp(
            DBHOST_SQL,
            {
                "project_id": "abcdefghijklmnopqrst",
                "query": "INSERT INTO t (a) VALUES ('secret value')",
                "access_token": "tok-123",
            },
        ),
        UNRELATED,
        shipped,
    )
    state = r.bodies[0]["state"]
    assert state["tool"] == DBHOST_SQL
    assert "secret value" not in state["input"]
    assert "tok-123" not in state["input"]
    assert "INSERT INTO t" in state["input"]
    assert state["notes"] == []


@pytest.mark.parametrize(
    ("answer", "env"),
    [
        ({"kind": "hang"}, {"GATE_JEV_TIMEOUT_MS": "200"}),
        ({"kind": "status", "status": 429}, {"GATE_JEV_TIMEOUT_MS": "400"}),
        ({"kind": "status", "status": 529}, {"GATE_JEV_TIMEOUT_MS": "400"}),
        ({"kind": "status", "status": 401}, {}),
        ({"kind": "malformed"}, {}),
    ],
    ids=["hang", "429", "529", "401", "malformed"],
)
def test_jev_failures_give_rule_result(run_jev, shipped, answer, env):
    def go(stdin):
        return run_jev(stdin, answer, {**shipped, **env})

    assert reason(go(bash("terraform apply")).stdout).startswith("terraform:")
    assert go(bash("git status")).stdout == ""
    assert reason(go(mcp(DBHOST_SQL, {"query": "SELECT 1"})).stdout).startswith("dbhost-mcp:")
    assert go(mcp(ISSUE_EDIT, {"issueIdOrKey": "PROJ-1"})).stdout == ""


def test_mcp_without_args_and_gate_config_never_reach_jev(run_jev, shipped, bad_rules):
    no_args = run_jev(mcp(CLOUDCTL_MCP, {}), UNRELATED, shipped)
    assert reason(no_args.stdout).startswith("unparsable:")
    bad = run_jev(mcp(ISSUE_EDIT, {}), UNRELATED, {"GATE_RULES": str(bad_rules)})
    assert reason(bad.stdout).startswith("gate-config")
    assert no_args.hits + bad.hits == 0


def test_audit_log_records_tool_usage_latency(run_jev, shipped, tmp_path):
    log = tmp_path / "audit.jsonl"
    r = run_jev(mcp(DBHOST_SQL, {"query": "SELECT 1"}), READ_ONLY, {**shipped, "GATE_JEV_LOG": str(log)})
    assert r.stdout == ""
    record = json.loads(log.read_text().strip().split("\n")[0])
    assert record["tool"] == DBHOST_SQL
    assert record["usage"] == {"input_tokens": 1000, "output_tokens": 10}
    assert isinstance(record["latencyMs"], (int, float))
    assert record["decision"] == "pass"
    assert record["rule"].startswith("dbhost-mcp:")
