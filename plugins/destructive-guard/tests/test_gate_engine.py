"""Gate engine (port of gate-engine.test.mjs; the classify cases are tests/cases/gate_engine.json).

Reasons go through `check --json` (and in-process through `classify`), the CLI rows through the
hook; `split_command` and `load_rules` run in-process.
"""

import json

import pytest

from destructive_guard.engine.classifier import Classifier
from destructive_guard.errors import RulesError, UnparsableError
from destructive_guard.rules.rule_loader import RuleLoader
from destructive_guard.shell.tokenizer import ShellTokenizer
from testkit import DG, REPO
from testkit.check_cli import CheckRunner
from testkit.hook import HookRunner

ENGINE_RULES = DG / "tests" / "fixtures" / "engine_rules.json"
CORPUS_ENV = {"GATE_CHECKS": "none", "GATE_RULES_FILE": str(ENGINE_RULES), "GATE_STRICT": "1"}
CLI_ENV = {"GATE_RULES": str(ENGINE_RULES), "CLAUDE_PROJECT_DIR": str(REPO)}


def reason(impl, command, cwd):
    return CheckRunner.check_call(impl, {"bash": command}, env=CORPUS_ENV, cwd=cwd)["reason"]


def load_rules(path):
    return RuleLoader.load_rules(path)


def raises(name, fn):
    expected = {"RulesError": RulesError, "UnparsableError": UnparsableError}[name]
    with pytest.raises(expected):
        fn()


def write_json(path, value):
    path.write_text(json.dumps(value))
    return path


# --- reasons (through check --json) ---


def test_allowlist_reasons_name_the_write_verb(impl, tmp_path):
    assert reason(impl, "cloudctl things delete config get", tmp_path) == 'cloudctl: write verb "delete"'
    assert reason(impl, "cloudctl version apply", tmp_path) == 'cloudctl: write verb "apply"'


def test_dynamic_arguments_name_the_reason(impl, tmp_path):
    assert reason(impl, "dbtool $ACTION", tmp_path) == "dbtool: dynamic argument"
    assert reason(impl, "echo push | xargs dbtool", tmp_path) == "dbtool: dynamic argument"


def test_shell_reading_stdin_reason(impl, tmp_path):
    assert reason(impl, "echo x | bash", tmp_path) == "unparsable: shell reads stdin"
    assert reason(impl, 'eval "$CMD"', tmp_path) == "unparsable: dynamic shell command"


@pytest.mark.parametrize("stdin", ["null", '"x"'])
def test_non_object_input_fails_closed(impl, stdin):
    out = HookRunner.run(impl, stdin, CLI_ENV).stdout
    assert HookRunner.decision(out)["permissionDecisionReason"].startswith("unparsable:")


# --- classify (in-process) ---


@pytest.fixture(scope="module")
def engine_rules():
    return load_rules(ENGINE_RULES)


def bash_input(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def test_classify_reasons_in_process(engine_rules):
    def why(command):
        return Classifier(engine_rules).classify(bash_input(command))["reason"]

    assert why("cloudctl things delete config get") == 'cloudctl: write verb "delete"'
    assert why("cloudctl version apply") == 'cloudctl: write verb "apply"'
    assert why("dbtool $ACTION") == "dbtool: dynamic argument"
    assert why("echo push | xargs dbtool") == "dbtool: dynamic argument"
    assert why("echo x | bash") == "unparsable: shell reads stdin"
    assert why('eval "$CMD"') == "unparsable: dynamic shell command"
    assert Classifier(engine_rules).classify(bash_input("ls")) is None


def test_classify_marks_unparsable_commands(engine_rules):
    result = Classifier(engine_rules).classify(bash_input('echo "x'))
    assert result == {
        "decision": "ask",
        "reason": "unparsable: unterminated double quote",
        "commandUnparsable": True,
    }
    assert Classifier(engine_rules, False).classify(bash_input('echo "x')) is None


def test_classify_loose_still_checks_the_readable_parts(engine_rules):
    result = Classifier(engine_rules, False).classify(bash_input('echo "x; dbtool push'))
    assert result is None  # the whole string is unreadable: no opinion
    result = Classifier(engine_rules, False).classify(bash_input("bash -c 'echo $HOME' && dbtool push"))
    assert result["reason"].startswith("dbtool:")


@pytest.mark.parametrize("value", [None, "x", ["a"], 3])
def test_classify_non_object_input(engine_rules, value):
    assert Classifier(engine_rules).classify(value) == {"decision": "ask", "reason": "unparsable: hook input is not an object"}


def test_classify_input_level_failures_always_ask(engine_rules):
    for strict in (True, False):
        assert Classifier(engine_rules, strict).classify({})["reason"] == "unparsable: hook input has no tool_name"
        assert Classifier(engine_rules, strict).classify({"tool_name": "Bash"})["reason"] == "unparsable: Bash call has no command"
        assert Classifier(engine_rules, strict).classify({"tool_name": "Bash", "tool_input": []})["decision"] == "ask"


# --- splitCommand / loadRules ---


def test_split_command():
    assert ShellTokenizer.split_command('a b && c "d e"; f') == [["a", "b"], ["c", "d e"], ["f"]]
    raises("UnparsableError", lambda: ShellTokenizer.split_command('echo "x'))
    raises("UnparsableError", lambda: ShellTokenizer.split_command("(echo x"))


def test_load_rules_runners(tmp_path):
    legacy = next(r for r in load_rules(ENGINE_RULES)["runners"] if r["program"] == "legacy")
    assert legacy["subcommands"] == ["exec"]
    p = tmp_path / "r.json"
    write_json(p, {"runners": [{"valueOptions": []}]})
    raises("RulesError", lambda: load_rules(p))
    write_json(p, {"runners": [{"program": "x", "bareBin": 1}]})
    raises("RulesError", lambda: load_rules(p))


def test_load_rules_bad_config(tmp_path):
    a = tmp_path / "a.json"
    a.write_text("{not json")
    raises("RulesError", lambda: load_rules(a))
    b = write_json(tmp_path / "b.json", {"rules": [{"id": "x", "kind": "nope"}]})
    raises("RulesError", lambda: load_rules(b))
    c = write_json(tmp_path / "c.json", {"rules": [{"id": "x", "kind": "mcp-allowlist", "tool": "("}]})
    raises("RulesError", lambda: load_rules(c))
    raises("RulesError", lambda: load_rules(tmp_path / "missing.json"))


def test_load_rules_legacy_and_removed_kinds(tmp_path):
    p = write_json(tmp_path / "r.json", {"protectedBranches": ["main"], "rules": []})
    assert load_rules(p)["rules"] == []
    for kind in ("script", "git-push"):
        write_json(p, {"rules": [{"id": "x", "kind": kind, "pathPattern": "x"}]})
        raises("RulesError", lambda: load_rules(p))


def test_load_rules_inert_unsafe_flags(tmp_path):
    p = tmp_path / "r.json"
    for bad in ("rg", ["--pre"], None, {"rg": "--pre"}, {"rg": [1]}, {"rg": [""]}):
        write_json(p, {"inertUnsafeFlags": bad})
        raises("RulesError", lambda: load_rules(p))
    write_json(p, {"inertUnsafeFlags": {"rg": ["--pre"]}})
    assert load_rules(p)["inertUnsafeFlags"] == {"rg": ["--pre"]}


# --- CLI rows (the hook entry) ---


def hook_stdin(tool_name, tool_input, **extra):
    return json.dumps({"tool_name": tool_name, "tool_input": tool_input, "cwd": str(REPO), **extra})


def test_cli_gated_command_asks(impl):
    r = HookRunner.run(impl, hook_stdin("Bash", {"command": "dbtool push"}), CLI_ENV)
    assert r.status == 0
    d = HookRunner.decision(r.stdout)
    assert d["hookEventName"] == "PreToolUse"
    assert d["permissionDecision"] == "ask"
    assert d["permissionDecisionReason"].startswith("dbtool:")


def test_cli_non_gated_prints_nothing(impl):
    r = HookRunner.run(impl, hook_stdin("Bash", {"command": "ls"}), CLI_ENV)
    assert r.status == 0
    assert r.stdout.strip() == ""


def test_cli_subagent_call_still_asks(impl):
    r = HookRunner.run(impl, hook_stdin("Bash", {"command": "dbtool push"}, agent_id="agent-123"), CLI_ENV)
    assert r.status == 0
    assert HookRunner.decision(r.stdout)["permissionDecision"] == "ask"


def test_cli_broken_rules_asks_gate_config(impl, bad_rules):
    r = HookRunner.run(impl, hook_stdin("Read", {"file_path": "/x"}), CLI_ENV, {"GATE_RULES": str(bad_rules)})
    assert r.status == 0
    d = HookRunner.decision(r.stdout)
    assert d["permissionDecision"] == "ask"
    assert d["permissionDecisionReason"].startswith("gate-config:")


def test_cli_unparsable_stdin_asks(impl):
    r = HookRunner.run(impl, "not json", CLI_ENV)
    assert r.status == 0
    d = HookRunner.decision(r.stdout)
    assert d["permissionDecision"] == "ask"
    assert d["permissionDecisionReason"].startswith("unparsable:")
