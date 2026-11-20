"""Rule packs (port of packs.test.mjs).

# retarget to destructive_guard in P5
The pack helpers have no CLI surface, so they go through the JS bridge for now.
"""

import json
import re

import pytest

from testkit import DG
from testkit.bridge import BridgeError, bridge
from testkit.hook import bash_input, decision, run_hook

FIXTURE = json.loads((DG / "tests" / "fixtures" / "rules.json").read_text())


def pack_path(name):
    return bridge("gate-engine", "packPath", name)


def compose(paths):
    return bridge("gate-engine", "composeRules", paths)


def raises_rules_error(fn):
    with pytest.raises(BridgeError) as e:
        fn()
    assert e.value.name == "RulesError"


def test_ported_packs_match_the_test_ruleset():
    composed = compose([pack_path(n) for n in ("base", "postgres", "terraform")])
    for key in ("wrappers", "runners", "inertPrograms", "inertUnsafeFlags"):
        assert composed[key] == FIXTURE[key], key
    for p in composed["scriptPatterns"]:
        assert p in FIXTURE["scriptPatterns"], p
    for rule in composed["rules"]:
        assert rule == next(r for r in FIXTURE["rules"] if r["id"] == rule["id"]), rule["id"]
    assert sorted(r["id"] for r in composed["rules"]) == ["pg_restore", "psql", "terraform"]
    assert composed["scriptScanExempt"] == []


@pytest.mark.parametrize("name", ["destructive", "postgres", "terraform"])
def test_every_pack_loads_after_base(name):
    bridge("gate-engine", "loadPacks", [pack_path("base"), pack_path(name)])


def test_compose_rejects_duplicates_and_bad_shapes(tmp_path):
    def write(name, obj):
        p = tmp_path / name
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
        return str(p)

    a = write("a.json", {"rules": [{"id": "x", "kind": "cli-gated", "programs": ["x"], "gatedPrefixes": [[]]}]})
    raises_rules_error(lambda: compose([a, a]))
    raises_rules_error(lambda: compose([write("b.json", "[]")]))
    raises_rules_error(lambda: compose([write("c.json", "{nope")]))
    raises_rules_error(lambda: compose([write("d.json", {"inertUnsafeFlags": {"rg": "x"}})]))
    raises_rules_error(lambda: compose([str(tmp_path / "missing.json")]))


def test_compose_merges_string_lists_without_duplicates(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"inertPrograms": ["ls", "cat"], "inertUnsafeFlags": {"rg": ["--pre"]}}))
    b.write_text(json.dumps({"inertPrograms": ["cat", "wc"], "inertUnsafeFlags": {"rg": ["--pre", "-z"]}}))
    m = compose([str(a), str(b)])
    assert m["inertPrograms"] == ["ls", "cat", "wc"]
    assert m["inertUnsafeFlags"] == {"rg": ["--pre", "-z"]}


def test_default_packs_is_base_and_destructive():
    assert bridge("gate-engine", "DEFAULT_PACKS") == ["base", "destructive"]


def test_without_gate_rules_hook_loads_default_packs(impl, tmp_path):
    def run(command):
        return run_hook(impl, bash_input(command, tmp_path), {"GATE_RULES": ""}, cwd=tmp_path).stdout

    asked = decision(run("terraform destroy"))
    assert asked["permissionDecision"] == "ask"
    assert re.match(r"^terraform-destroy:", asked["permissionDecisionReason"])
    assert re.match(r"^git-push-force:", decision(run("git push --force"))["permissionDecisionReason"])
    assert run("git push") == ""
    assert run("git status") == ""
    assert run("ls -la") == ""
