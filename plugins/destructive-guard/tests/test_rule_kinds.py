"""Inline rule capabilities through `check --json` (port of the inline-rule tests of destructive.test.mjs)."""

import json

import pytest

from testkit.check_cli import check_call


@pytest.fixture
def one(impl, tmp_path):
    """one(rule)(call) -> the check result with only `rule` loaded."""
    counter = iter(range(1000))

    def with_rule(rule):
        path = tmp_path / f"rules-{next(counter)}.json"
        path.write_text(json.dumps({"rules": [rule]}))
        env = {"GATE_CHECKS": "none", "GATE_RULES_FILE": str(path)}
        return lambda call: check_call(impl, call, env=env, cwd=tmp_path)

    return with_rule


def rule_id(result):
    return result["source"] if result["decision"] == "ask" else None


def bash(command):
    return {"bash": command}


def mcp(tool, tool_input=None):
    return {"mcp": tool, "input": tool_input or {}}


def test_when_flags_groups_and_short_bundles(one):
    base = {"id": "t", "kind": "cli-gated", "programs": ["t"], "gatedPrefixes": [[]], "whenFlags": [["-a"], ["-b"]]}
    strict = one(base)
    bundled = one({**base, "shortBundles": True})
    assert rule_id(strict(bash("t -a -b"))) == "t"
    assert rule_id(strict(bash("t -ab"))) is None
    assert rule_id(bundled(bash("t -ab"))) == "t"
    assert rule_id(bundled(bash("t -a"))) is None
    assert rule_id(bundled(bash("t -- -ab"))) is None


def test_unless_flags_exact_without_short_bundles(one):
    r = one({"id": "t", "kind": "cli-gated", "programs": ["t"], "gatedPrefixes": [[]], "unlessFlags": ["-f"]})
    assert r(bash("t -dfoo"))["reason"] == "t: gated invocation"
    assert r(bash("t -f x"))["decision"] == "none"


def test_dynamic_args_ask_vs_ignore(one):
    rule = {"id": "t", "kind": "cli-gated", "programs": ["t"], "gatedPrefixes": [["x"]]}
    assert one(rule)(bash("t $A"))["reason"] == "t: dynamic argument"
    ignore = one({**rule, "dynamicArgs": "ignore"})
    assert ignore(bash("t $A"))["decision"] == "none"
    assert ignore(bash("t x $A"))["reason"] == "t: gated invocation"


def test_when_args_ignore_case_and_match_stdin(one):
    rule = {"id": "t", "kind": "cli-gated", "programs": ["t"], "gatedPrefixes": [[]], "whenArgs": ["^BAD$"]}
    assert rule_id(one(rule)(bash("t bad"))) is None
    assert rule_id(one({**rule, "ignoreCase": True})(bash("t bad"))) == "t"
    assert rule_id(one(rule)(bash("t <<E\nBAD\nE"))) is None
    assert rule_id(one({**rule, "whenArgs": ["BAD"], "matchStdin": True})(bash("t <<E\nBAD\nE"))) == "t"


@pytest.mark.parametrize(
    "rule",
    [
        {"id": "t", "kind": "cli-gated", "programs": ["t"], "gatedPrefixes": [[]], **bad}
        for bad in (
            {"whenFlags": [[]]},
            {"whenFlags": ["-a"]},
            {"whenArgs": ["("]},
            {"shortBundles": "yes"},
            {"dynamicArgs": "maybe"},
            {"scriptScan": 1},
        )
    ]
    + [
        {"id": "m", "kind": "mcp-pattern"},
        {"id": "m", "kind": "mcp-pattern", "inputPattern": "("},
        {"id": "m", "kind": "mcp-pattern", "toolWords": [""]},
    ],
    ids=json.dumps,
)
def test_new_rule_fields_are_validated(one, rule):
    r = one(rule)(bash("t"))
    assert r["decision"] == "ask"
    assert r["source"] == "gate-config"


def test_mcp_pattern_tool_regex_and_camel_case_words(one):
    r = one({"id": "m", "kind": "mcp-pattern", "tool": "^mcp__danger__"})
    assert r(mcp("mcp__danger__anything"))["reason"] == "m: anything"
    assert r(mcp("mcp__safe__anything"))["decision"] == "none"
    w = one({"id": "w", "kind": "mcp-pattern", "toolWords": ["purge"]})
    assert rule_id(w(mcp("mcp__x__purgeCache"))) == "w"
    assert w(mcp("mcp__x__purgecache"))["decision"] == "none"
