"""Jev prompts (port of jev-prompt.test.mjs).

The prompt helpers run in-process; askJev goes through the check CLI (contract test).
"""

import json
import re

import pytest

from destructive_guard.errors import JevConfigError
from destructive_guard.jev.config import JevConfig
from destructive_guard.jev.judge import JevJudge
from destructive_guard.jev.prompt import JevPrompt
from testkit import DG
from testkit.hook import HookRunner

BASE_ENV = {"TYPESAFE_API_KEY": "key-123"}
JEV_DIR = DG / "jev"


def cfg_with(prompt):
    return {
        "apiKey": "k",
        "url": "https://example.test/v1",
        "model": "m",
        "timeoutMs": 500,
        "escalateThreshold": 0.5,
        "prompt": prompt,
    }


def d(read_only, reversible_change, destructive):
    return {"read_only": read_only, "reversible_change": reversible_change, "destructive": destructive}


CUSTOM = {
    "question": "risky",
    "instructions": "Is this risky?",
    "context": {"environment": "e"},
    "criteria": {
        "fine": {"description": "fine", "examples": ["ls"]},
        "risky": {"description": "risky", "examples": ["rm -rf /"]},
    },
    "ask": ["risky"],
    "safe": ["fine"],
}


def test_default_prompt_is_destructive_and_covers_local_and_remote():
    assert JevPrompt.DEFAULT_PROMPT == "destructive"
    p = JevConfig.read(BASE_ENV)["prompt"]
    assert p["question"] == "destructive"
    assert list(p["criteria"]) == ["read_only", "reversible_change", "destructive"]
    assert p["ask"] == ["destructive"]
    assert p["safe"] == ["read_only", "reversible_change"]
    assert re.search(r"local machine", p["instructions"])
    examples = "\n".join(p["criteria"]["destructive"]["examples"])
    for needle in (
        "rm -rf",
        "git reset --hard",
        "git clean -fdx",
        "git stash drop",
        "git push --force",
        "docker volume rm",
        "terraform destroy",
        "DROP TABLE",
        "an MCP tool call that deletes",
        "a script that runs",
    ):
        assert needle in examples, needle


@pytest.mark.parametrize("path", sorted(JEV_DIR.glob("*.json")), ids=lambda p: p.name)
def test_builtin_prompts_valid_and_generic(path):
    text = path.read_text()
    JevPrompt.validate_prompt(json.loads(text), path.name)
    assert not re.search(r"mcp__\w", text)
    assert not re.search(r"jira|atlassian|chrome|cloudflare|wrangler|supabase|gcloud|google", text, re.IGNORECASE)


def test_judge_with_destructive_prompt():
    cfg = cfg_with(JevPrompt.builtin_prompt("destructive"))
    out = JevJudge.judge({"probabilities": d(0.1, 0.2, 0.7)}, cfg)
    assert (out.decision, out.reason) == ("ask", "jev: destructive p=0.70 risk=0.70")
    assert JevJudge.judge({"probabilities": d(0.02, 0.96, 0.02)}, cfg).decision == "none"
    assert JevJudge.judge({"probabilities": d(0.3, 0.3, 0.4)}, cfg).decision == "none"


def test_safe_is_optional_but_validated_when_present():
    without = {k: v for k, v in CUSTOM.items() if k != "safe"}
    assert JevPrompt.validate_prompt(without) == without
    with pytest.raises(JevConfigError, match="safe"):
        JevPrompt.validate_prompt({**CUSTOM, "safe": []})


def test_hook_sends_destructive_question(impl, jev, tmp_path):
    jev.answer(d(0.05, 0.05, 0.9), question="destructive")
    env = {"TYPESAFE_API_KEY": "k", "GATE_JEV_URL": jev.url}
    r = HookRunner.run(impl, HookRunner.bash_input("rm -rf ~/work", tmp_path), env, cwd=tmp_path)
    [body] = jev.bodies
    assert list(body["questions"]) == ["destructive"]
    assert body["state"]["context"]["policy"] == JevPrompt.builtin_prompt("destructive")["context"]["policy"]
    assert HookRunner.decision(r.stdout)["permissionDecisionReason"].startswith("jev: ")


def test_prompt_env_selects_builtin_or_file(tmp_path):
    assert JevPrompt.prompt_from_env({"GATE_JEV_PROMPT": "cloud-change"})["question"] == "cloud_change"
    assert JevPrompt.prompt_from_env({"GATE_JEV_PROMPT": " "})["question"] == "destructive"
    path = tmp_path / "p.json"
    path.write_text(json.dumps(CUSTOM))
    assert JevPrompt.prompt_from_env({"GATE_JEV_PROMPT": str(path)}) == CUSTOM


def test_relative_prompt_resolves_against_project_dir(tmp_path):
    (tmp_path / "prompt.json").write_text(json.dumps(CUSTOM))
    env = {
        **BASE_ENV,
        "CLAUDE_PROJECT_DIR": str(tmp_path),
        "GATE_JEV_PROMPT": "./prompt.json",
    }
    cfg = JevConfig.read(env)
    assert cfg["prompt"] == CUSTOM


def test_instructions_context_policy_override_prompt():
    p = JevPrompt.prompt_from_env(
        {
            "GATE_JEV_INSTRUCTIONS": "Could this lose data?",
            "GATE_JEV_CONTEXT": "A monorepo; data/ holds fixtures that cannot be regenerated.",
            "GATE_JEV_POLICY": "Ask before anything that deletes files in data/.",
        },
    )
    builtin = JevPrompt.builtin_prompt("destructive")
    assert p["instructions"] == "Could this lose data?"
    assert p["context"]["project"] == "A monorepo; data/ holds fixtures that cannot be regenerated."
    assert p["context"]["policy"] == "Ask before anything that deletes files in data/."
    assert p["context"]["environment"] == builtin["context"]["environment"]
    # the built-in is not mutated
    assert builtin["instructions"] != "Could this lose data?"


def _bad_prompt_values(tmp_path):
    good = JevPrompt.builtin_prompt("destructive")

    def write(name, obj):
        p = tmp_path / name
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
        return str(p)

    return [
        "nope",
        "../lib/x",
        str(tmp_path / "missing.json"),
        write("syntax.json", "{"),
        write("overlap.json", {**good, "safe": ["read_only", "destructive"]}),
        write("unknown.json", {**good, "ask": ["catastrophic"]}),
        write("one.json", {**good, "criteria": {"a": good["criteria"]["read_only"]}, "ask": ["a"], "safe": ["a"]}),
        write("q.json", {**good, "question": "Bad Id"}),
        write("ctx.json", {**good, "context": {"a": 1}}),
        write("ex.json", {**good, "criteria": {**good["criteria"], "destructive": {"description": "x"}}}),
    ]


def test_bad_prompt_settings_raise_jev_config_error(tmp_path):
    for value in _bad_prompt_values(tmp_path):
        with pytest.raises(JevConfigError):
            JevConfig.read({**BASE_ENV, "GATE_JEV_PROMPT": value})
