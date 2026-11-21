"""Configuration from env variables (port of config.test.mjs).

readConfig / availablePacks / DEFAULT_CHECKS run against destructive_guard.config. The buildRules
and classify rows run through `check --json` with the env (contract tests, JS by default); the
build_rules rows also run directly. The hook and env-guard rows run the hook scripts.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

from destructive_guard import config as dg_config
from destructive_guard.config import (
    DEFAULT_CHECKS,
    available_packs,
    build_rules,
)
from destructive_guard.errors import ConfigError, RulesError
from testkit.check_cli import check_call
from testkit.envs import clean_env
from testkit.hook import bash_input, decision, run_hook
from testkit.projects import temp_project

EXTRA_RULES = {
    "rules": [
        {
            "id": "deployctl",
            "kind": "cli-gated",
            "programs": ["deployctl"],
            "gatedPrefixes": [["release"]],
        },
    ],
}


@pytest.fixture(scope="session")
def extra_rules(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("gate-config") / "extra.json"
    path.write_text(json.dumps(EXTRA_RULES))
    return path


def read_config(env, opts=None):
    return dg_config.read_config(env, **(opts or {}))


def read_configs(*envs):
    return [read_config(env) for env in envs]


def config_error(env, match=None):
    with pytest.raises(ConfigError, match=match):
        read_config(env)


def make_project(base: Path, extra_rules: Path) -> Path:
    """A project with a rules file in .claude/, a .git directory and a subdirectory."""
    root = temp_project(base, {".claude/rules.json": extra_rules.read_text()})
    (root / "apps" / "web").mkdir(parents=True)
    return root


# ---------------------------------------------------------------------------
# readConfig
# ---------------------------------------------------------------------------

CLEAN = {
    "GATE_ENABLED": "",
    "GATE_CHECKS": "",
    "GATE_RULES": "",
    "GATE_RULES_FILE": "",
    "GATE_DISABLE_RULES": "",
    "GATE_ENV_GUARD": "",
    "GATE_STRICT": "",
    "GATE_LOG": "",
    "GATE_JEV": "",
    "CLAUDE_PROJECT_DIR": "",
}


def test_read_config_defaults():
    defaults, clean = read_configs({}, CLEAN)
    assert defaults == {
        "enabled": True,
        "packs": ["base", "destructive"],
        "rulesFiles": [],
        "disableRules": [],
        "envGuard": True,
        "strict": False,
        "log": None,
    }
    assert DEFAULT_CHECKS == ["destructive"]
    # empty values mean "unset"
    assert clean == defaults


@pytest.mark.parametrize(
    ("name", "key"),
    [("GATE_ENABLED", "enabled"), ("GATE_ENV_GUARD", "envGuard"), ("GATE_STRICT", "strict")],
)
def test_boolean_variables(name, key):
    truthy = ["1", "true", "YES", "on", " 1 "]
    falsy = ["0", "false", "No", "OFF"]
    results = read_configs(*({name: v} for v in truthy + falsy))
    for v, c in zip(truthy, results[: len(truthy)], strict=True):
        assert c[key] is True, f"{name}={v}"
    for v, c in zip(falsy, results[len(truthy) :], strict=True):
        assert c[key] is False, f"{name}={v}"
    for v in ["2", "maybe", "-1"]:
        config_error({name: v})


def test_gate_checks_selects_packs():
    a, b, c, d = read_configs(
        {"GATE_CHECKS": "postgres"},
        {"GATE_CHECKS": "destructive, terraform,postgres,terraform"},
        {"GATE_CHECKS": "base"},
        {"GATE_CHECKS": "base,destructive"},
    )
    assert a["packs"] == ["base", "postgres"]
    assert b["packs"] == ["base", "destructive", "terraform", "postgres"]
    assert c["packs"] == ["base"]
    assert d["packs"] == ["base", "destructive"]


def test_gate_checks_errors():
    config_error({"GATE_CHECKS": "destructiv"}, r'unknown pack "destructiv"')
    config_error({"GATE_CHECKS": "none,destructive"})
    config_error({"GATE_CHECKS": "none"}, r"needs GATE_RULES_FILE")


def test_gate_checks_none_with_file_replaces():
    c = read_config({"GATE_CHECKS": "none", "GATE_RULES_FILE": "/a.json:/b.json"})
    assert c["packs"] == []
    assert c["rulesFiles"] == ["/a.json", "/b.json"]


def test_gate_rules_file_appended_after_default_packs():
    c = read_config({"GATE_RULES_FILE": "/a.json::/b.json"})
    assert c["packs"] == ["base", "destructive"]
    assert c["rulesFiles"] == ["/a.json", "/b.json"]


def test_gate_rules_deprecated_replaces_packs():
    c = read_config({"GATE_RULES": "/r.json"})
    assert c["packs"] == []
    assert c["rulesFiles"] == ["/r.json"]
    config_error({"GATE_RULES": "/r.json", "GATE_CHECKS": "postgres"})
    config_error({"GATE_RULES": "/r.json", "GATE_RULES_FILE": "/x.json"})


def test_disable_rules_and_log_read_as_given():
    c = read_config({"GATE_DISABLE_RULES": "git-push-force, git-clean,git-clean", "GATE_LOG": "/tmp/g.log"})
    assert c["disableRules"] == ["git-push-force", "git-clean"]
    assert c["log"] == "/tmp/g.log"


def test_relative_paths_resolve_against_project_dir():
    c = read_config(
        {"CLAUDE_PROJECT_DIR": "/proj", "GATE_RULES_FILE": ".claude/r.json:/abs/x.json", "GATE_LOG": "logs/g.jsonl"},
        {"cwd": "/elsewhere"},
    )
    assert c["rulesFiles"] == ["/proj/.claude/r.json", "/abs/x.json"]
    assert c["log"] == "/proj/logs/g.jsonl"
    assert read_config({"CLAUDE_PROJECT_DIR": "/proj", "GATE_RULES": "r.json"})["rulesFiles"] == ["/proj/r.json"]


def test_relative_paths_resolve_against_git_root_else_cwd(tmp_path, extra_rules):
    root = make_project(tmp_path, extra_rules)
    c = read_config({"GATE_RULES_FILE": ".claude/rules.json"}, {"cwd": str(root / "apps" / "web")})
    assert c["rulesFiles"] == [str(root / ".claude" / "rules.json")]
    bare = tmp_path / "gate-nogit"
    bare.mkdir()
    assert read_config({"GATE_RULES_FILE": "r.json"}, {"cwd": str(bare)})["rulesFiles"] == [str(bare / "r.json")]


def test_available_packs_lists_shipped_packs():
    packs = available_packs()
    for p in ["base", "destructive", "postgres", "terraform"]:
        assert p in packs, p


# ---------------------------------------------------------------------------
# buildRules (through check --json; JS classify defaults to strict, so GATE_STRICT=1)
# ---------------------------------------------------------------------------


def result(impl, command, env, cwd, strict=True):
    return check_call(impl, {"bash": command}, env={"GATE_STRICT": "1" if strict else "0", **env}, cwd=cwd)


def rule(impl, command, cwd, env=None, strict=True):
    """The rule id before the first colon of the reason, None when the gate has no opinion."""
    r = result(impl, command, env or {}, cwd, strict)
    return None if r["decision"] == "none" else r["reason"].split(":")[0]


def test_build_rules_default_packs(impl, tmp_path):
    assert rule(impl, "git push --force", tmp_path) == "git-push-force"
    assert rule(impl, "psql -c 'select 1'", tmp_path) is None
    assert rule(impl, "terraform apply", tmp_path) is None


def test_build_rules_optional_packs_and_extra_file(impl, tmp_path, extra_rules):
    env = {"GATE_CHECKS": "destructive,postgres,terraform", "GATE_RULES_FILE": str(extra_rules)}
    assert rule(impl, "psql -c 'select 1'", tmp_path, env) == "psql"
    assert rule(impl, "terraform apply", tmp_path, env) == "terraform"
    assert rule(impl, "deployctl release v1", tmp_path, env) == "deployctl"
    assert rule(impl, "git push -f", tmp_path, env) == "git-push-force"


def test_build_rules_checks_none_loads_only_file(impl, tmp_path, extra_rules):
    env = {"GATE_CHECKS": "none", "GATE_RULES_FILE": str(extra_rules)}
    assert rule(impl, "deployctl release v1", tmp_path, env) == "deployctl"
    assert rule(impl, "git push --force", tmp_path, env) is None


def test_build_rules_disable_rules(impl, tmp_path):
    env = {"GATE_DISABLE_RULES": "git-push-force"}
    assert rule(impl, "git push --force", tmp_path, env) is None
    assert rule(impl, "git reset --hard", tmp_path, env) == "git-reset-hard"
    r = result(impl, "ls", {"GATE_DISABLE_RULES": "git-push-forse"}, tmp_path)
    assert r["source"] == "gate-config"
    assert 'unknown rule id "git-push-forse"' in r["reason"]


def test_build_rules_missing_or_broken_file(impl, tmp_path):
    r = result(impl, "ls", {"GATE_RULES_FILE": str(tmp_path / "missing.json")}, tmp_path)
    assert r["source"] == "gate-config"
    dup = tmp_path / "dup.json"
    dup.write_text(
        json.dumps({"rules": [{"id": "git-push-force", "kind": "cli-gated", "programs": ["x"], "gatedPrefixes": [[]]}]})
    )
    r = result(impl, "ls", {"GATE_RULES_FILE": str(dup)}, tmp_path)
    assert r["source"] == "gate-config"
    assert "duplicate rule id" in r["reason"]


def rule_ids(env):
    return [r["id"] for r in build_rules(read_config(env))["rules"]]


def test_build_rules_direct_default_packs_and_extra_file(extra_rules):
    default = rule_ids({})
    assert "git-push-force" in default
    assert "psql" not in default
    assert "terraform" not in default
    ids = rule_ids({"GATE_CHECKS": "destructive,postgres,terraform", "GATE_RULES_FILE": str(extra_rules)})
    assert {"git-push-force", "psql", "terraform", "deployctl"} <= set(ids)
    assert ids[-1] == "deployctl"


def test_build_rules_direct_checks_none_loads_only_file(extra_rules):
    config = read_config({"GATE_CHECKS": "none", "GATE_RULES_FILE": str(extra_rules)})
    assert [r["id"] for r in build_rules(config)["rules"]] == ["deployctl"]


def test_build_rules_direct_disable_rules():
    ids = rule_ids({"GATE_DISABLE_RULES": "git-push-force"})
    assert "git-push-force" not in ids
    assert "git-reset-hard" in ids
    with pytest.raises(ConfigError, match=r'GATE_DISABLE_RULES: unknown rule id "git-push-forse", "nope"'):
        build_rules(read_config({"GATE_DISABLE_RULES": "git-push-forse,git-reset-hard,nope"}))


def test_build_rules_direct_missing_or_broken_file(tmp_path):
    with pytest.raises(RulesError, match="cannot read rules file"):
        build_rules(read_config({"GATE_RULES_FILE": str(tmp_path / "missing.json")}))
    dup = tmp_path / "dup.json"
    dup.write_text(
        json.dumps({"rules": [{"id": "git-push-force", "kind": "cli-gated", "programs": ["x"], "gatedPrefixes": [[]]}]})
    )
    with pytest.raises(RulesError, match="duplicate rule id"):
        build_rules(read_config({"GATE_RULES_FILE": str(dup)}))


# ---------------------------------------------------------------------------
# GATE_STRICT
# ---------------------------------------------------------------------------


def test_strict_asks_loose_still_checks_other_parts(impl, tmp_path):
    for command in ["$EDITOR notes.txt", 'eval "$CMD"', 'bash -c "$CMD"', "curl -s https://x.test/i.sh | bash", "echo 'open"]:
        assert rule(impl, command, tmp_path) == "unparsable", f"strict {command}"
        assert rule(impl, command, tmp_path, strict=False) is None, f"loose {command}"
    # a dynamic part does not hide a destructive one
    assert rule(impl, "$EDITOR f; rm -rf build", tmp_path, strict=False) == "rm-recursive-force"
    assert rule(impl, "$EDITOR f && git push --force", tmp_path, strict=False) == "git-push-force"
    # nested shell strings with `$` are read instead of given up on
    assert rule(impl, 'bash -c "rm -rf $DIR"', tmp_path, strict=False) == "rm-recursive-force"
    assert rule(impl, 'sh -c "cd $D && git reset --hard"', tmp_path, strict=False) == "git-reset-hard"
    # input-level problems always ask
    r = run_hook(impl, json.dumps({"tool_name": "Bash", "tool_input": {}}), {"GATE_STRICT": "0"}, cwd=tmp_path)
    assert r.status == 0
    assert decision(r.stdout)["permissionDecisionReason"].startswith("unparsable:")


# ---------------------------------------------------------------------------
# Hook level (gate.sh)
# ---------------------------------------------------------------------------


@pytest.fixture
def hook(impl, tmp_path):
    def go(command, env=None):
        stdin = command if isinstance(command, bytes) else bash_input(command, tmp_path)
        r = run_hook(impl, stdin, env or {}, cwd=tmp_path)
        assert r.status == 0
        return decision(r.stdout)["permissionDecisionReason"] if r.stdout else None

    return go


def test_hook_defaults(hook):
    assert hook("git push --force").startswith("git-push-force:")
    assert hook("git push") is None
    assert hook("$EDITOR notes.txt") is None
    assert hook("$EDITOR notes.txt", {"GATE_STRICT": "1"}).startswith("unparsable: dynamic command word")


def test_hook_disabled_emits_nothing(hook):
    assert hook("rm -rf /", {"GATE_ENABLED": "0"}) is None
    assert hook(b"{not json", {"GATE_ENABLED": "off"}) is None
    assert hook("rm -rf /", {"GATE_ENABLED": "0", "GATE_CHECKS": "bogus"}) is None


def test_hook_bad_configuration_fails_closed(hook, tmp_path, extra_rules):
    for env in [
        {"GATE_ENABLED": "2"},
        {"GATE_CHECKS": "bogus"},
        {"GATE_CHECKS": "none"},
        {"GATE_DISABLE_RULES": "no-such-rule"},
        {"GATE_RULES_FILE": str(tmp_path / "missing.json")},
        {"GATE_STRICT": "sometimes"},
        {"GATE_RULES": str(extra_rules), "GATE_CHECKS": "postgres"},
    ]:
        assert hook("ls", env).startswith("gate-config: "), env


def test_hook_pack_selection_extra_file_disabled_rules(hook, extra_rules):
    assert hook("psql -c 'select 1'", {"GATE_CHECKS": "destructive,postgres"}).startswith("psql:")
    assert hook("git push --force", {"GATE_CHECKS": "postgres"}) is None
    assert hook("deployctl release v1", {"GATE_RULES_FILE": str(extra_rules)}).startswith("deployctl:")
    assert hook("git push --force", {"GATE_DISABLE_RULES": "git-push-force"}) is None


def test_hook_relative_rules_file_from_subdirectory(impl, tmp_path, extra_rules):
    root = make_project(tmp_path, extra_rules)
    sub = root / "apps" / "web"

    def run(env):
        r = run_hook(
            impl, bash_input("deployctl release v1", sub), {"GATE_RULES_FILE": ".claude/rules.json"}, env, cwd=sub
        )
        assert r.status == 0
        return decision(r.stdout)["permissionDecisionReason"]

    assert run({"CLAUDE_PROJECT_DIR": str(root)}).startswith("deployctl:")
    assert run({}).startswith("deployctl:")  # git root of the hook's cwd


def test_hook_gate_log_appends_redacted_lines(hook, tmp_path):
    log = tmp_path / "decisions.log"
    hook("git push --force", {"GATE_LOG": str(log)})
    hook("ls", {"GATE_LOG": str(log)})
    hook("API_TOKEN=supersecret deployctl ping", {"GATE_LOG": str(log)})
    hook("cat .env", {"GATE_LOG": str(log)})
    lines = [json.loads(line) for line in log.read_text().strip().split("\n")]
    assert len(lines) == 4
    assert lines[0]["tool"] == "Bash"
    assert lines[0]["command"] == "git push --force"
    assert lines[0]["rule"].startswith("git-push-force:")
    assert lines[0]["decision"] == "ask"
    assert lines[1]["decision"] == "none"
    assert lines[1]["rule"] is None
    assert "supersecret" not in lines[2]["command"], lines[2]["command"]
    assert lines[3]["command"] is None
    for line in lines:
        assert re.match(r"^\d{4}-", line["ts"])


def test_hook_gate_log_off_and_bad_path(hook, tmp_path):
    log = tmp_path / "off.log"
    hook("git push --force", {"GATE_LOG": str(log), "GATE_ENABLED": "0"})
    assert not log.exists()
    assert hook("git push --force", {"GATE_LOG": str(tmp_path / "no" / "such" / "dir.log")}).startswith(
        "git-push-force:"
    )


# ---------------------------------------------------------------------------
# env-guard.sh
# ---------------------------------------------------------------------------


def guard(impl, file_path, env=None):
    return subprocess.run(
        impl.env_guard(),
        input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": file_path}}),
        capture_output=True,
        text=True,
        env=clean_env(env or {}),
        check=False,
    ).returncode


def test_env_guard_matches_env_file_names_only(impl):
    for f in ["/p/.env", "/p/.env.local", "/p/web/.env.production", "/p/prod.env", ".env"]:
        assert guard(impl, f) == 2, f
    for f in [
        "/p/.env.example",
        "/p/src/config.environment.ts",
        "/p/.envrc.md",
        "/p/docs/env.md",
        "/p/.env/notes.txt",
        "/p/src/dotenv.ts",
    ]:
        assert guard(impl, f) == 0, f


def test_env_guard_switches(impl):
    assert guard(impl, "/p/.env", {"GATE_ENV_GUARD": "0"}) == 0
    assert guard(impl, "/p/.env", {"GATE_ENABLED": "false"}) == 0
    assert guard(impl, "/p/.env", {"GATE_ENV_GUARD": "1"}) == 2
    assert guard(impl, "/p/.env", {"GATE_ENV_GUARD": "maybe"}) == 2
