"""Rule loading and pack composition (destructive_guard.rules)."""

import json

import pytest

from destructive_guard.errors import RulesError
from destructive_guard.rules.js_regex import JsRegex
from destructive_guard.rules.rule_loader import RuleLoader
from destructive_guard.rules.rule_parser import RuleParser

PACKS = sorted(p.stem for p in RuleLoader.PACKS_DIR.glob("*.json"))


def write(path, obj):
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj))
    return path


def test_constants():
    assert RuleLoader.DEFAULT_PACKS == ["base", "destructive"]
    assert RuleLoader.pack_path("base") == str(RuleLoader.PACKS_DIR / "base.json")
    assert PACKS == ["base", "destructive", "postgres", "terraform"]


def test_every_pack_regex_compiles():
    for name in PACKS:
        rules = RuleLoader.load_packs([RuleLoader.pack_path("base"), RuleLoader.pack_path(name)] if name != "base" else [RuleLoader.pack_path("base")])
        assert rules["rules"] or name == "base", name


def test_regex_translation():
    assert JsRegex.compile_js_regex(r"^a$").search("a\n") is None
    assert JsRegex.compile_js_regex(r"[$]").search("$")
    assert JsRegex.compile_js_regex(r"\$x").search("$x")
    assert JsRegex.compile_js_regex(r"(?<n>a)\1?").search("a")
    assert JsRegex.compile_js_regex("(?<!a)b").search("cb")
    assert JsRegex.compile_js_regex(r"\d").search("٣") is None  # JS \d is ASCII
    assert JsRegex.compile_js_regex("ab", "i").search("AB")


def test_load_rules_errors_name_the_problem(tmp_path):
    p = tmp_path / "r.json"
    cases = {
        "{not json": r"^cannot read rules file .*r\.json",
        "[]": r"^rules file must contain a JSON object",
        '{"rules": {}}': r"^rules must be an array",
        '{"rules": [{"kind": "cli-gated"}]}': r"^rule #0 needs a string id",
        '{"rules": [{"id": "x"}]}': r'^rule "x" has unknown kind "undefined"',
        '{"rules": [{"id": "x", "kind": null}]}': r'^rule "x" has unknown kind "null"',
        '{"rules": [{"id": "x", "kind": "cli-gated", "programs": "a"}]}': r"^rule \"x\" programs must be an array of strings",
        '{"rules": [{"id": "x", "kind": "cli-gated", "whenFlags": [[]]}]}': r"whenFlags groups must be non-empty",
        '{"rules": [{"id": "x", "kind": "cli-gated", "dynamicArgs": null}]}': r'dynamicArgs must be "ask" or "ignore"',
        '{"rules": [{"id": "x", "kind": "cli-gated", "scriptScan": null}]}': r"scriptScan must be a boolean",
        '{"rules": [{"id": "x", "kind": "mcp-pattern"}]}': r"needs tool, toolWords or inputPattern",
        '{"rules": [{"id": "x", "kind": "mcp-pattern", "toolWords": [""]}]}': r"toolWords must not contain empty strings",
        '{"rules": [{"id": "x", "kind": "mcp-allowlist"}]}': r"tool must be a regex string",
        '{"rules": [{"id": "x", "kind": "mcp-as-cli", "tool": "a"}]}': r"needs string argsField and program",
        '{"rules": [{"id": "x", "kind": "mcp-allowlist", "tool": "("}]}': r"tool is not a valid regex: ",
        '{"runners": {}}': r"^runners must be an array",
        '{"runners": [["a", "b", "c"]]}': r'^runner #0 must be \["program"\] or \["program", "sub"\]',
        '{"runners": [{"program": "x", "bareBin": 1}]}': r"runner #0 bareBin must be a boolean",
        '{"inertUnsafeFlags": {"rg": [""]}}': r"^inertUnsafeFlags rg must be an array of non-empty strings",
        '{"inertUnsafeFlags": []}': r"^inertUnsafeFlags must be an object of string arrays",
        '{"scriptPatterns": ["("]}': r"^scriptPatterns entry is not a valid regex",
        '{"scriptScanExempt": [""]}': r"^scriptScanExempt must not contain empty strings",
        '{"wrappers": null}': r"^wrappers must be an array of strings",
    }
    for text, match in cases.items():
        write(p, text)
        with pytest.raises(RulesError, match=match):
            RuleLoader.load_rules(p)
    with pytest.raises(RulesError, match="cannot read rules file"):
        RuleLoader.load_rules(tmp_path / "missing.json")
    with pytest.raises(RulesError, match="cannot read rules file"):
        write(p, '{"x": NaN}')
        RuleLoader.load_rules(p)


def test_runners_legacy_forms_merge(tmp_path):
    p = write(
        tmp_path / "r.json",
        {"runners": [["npx"], ["pnpm", "exec"], {"program": "pnpm", "valueOptions": ["-C"]}, ["pnpm", "dlx"]]},
    )
    runners = {r["program"]: r for r in RuleLoader.load_rules(p)["runners"]}
    assert runners["npx"] == {"program": "npx", "valueOptions": [], "subcommands": [], "shellOptions": [], "bareBin": True}
    assert runners["pnpm"]["subcommands"] == ["exec", "dlx"]
    assert runners["pnpm"]["valueOptions"] == ["-C"]


def test_parse_rules_defaults():
    parsed = RuleParser.parse_rules({"rules": [{"id": "g", "kind": "cli-gated"}, {"id": "m", "kind": "mcp-pattern", "toolWords": ["Drop"]}]})
    g, m = parsed["rules"]
    assert g["scriptScan"] is True
    assert g["dynamicArgs"] == "ask"
    assert g["whenArgs"] == []
    assert m["tool"].pattern == "^mcp__"
    assert m["toolWords"] == ["drop"]
    assert m["inputPattern"] is None
    assert RuleParser.parse_rules({}) == {
        "wrappers": [],
        "runners": [],
        "inertPrograms": [],
        "inertUnsafeFlags": {},
        "scriptPatterns": [],
        "scriptScanExempt": [],
        "rules": [],
    }


def test_when_args_follow_ignore_case():
    rule = RuleParser.parse_rules({"rules": [{"id": "g", "kind": "cli-gated", "whenArgs": ["^PROD"], "ignoreCase": True}]})["rules"][0]
    assert rule["whenArgs"][0].search("prod-1")
    rule = RuleParser.parse_rules({"rules": [{"id": "g", "kind": "cli-gated", "whenArgs": ["^PROD"]}]})["rules"][0]
    assert rule["whenArgs"][0].search("prod-1") is None


def test_compose_errors(tmp_path):
    a = write(tmp_path / "a.json", {"rules": [{"id": "x", "kind": "cli-gated", "programs": ["x"], "gatedPrefixes": [[]]}]})
    with pytest.raises(RulesError, match=r'a\.json: duplicate rule id "x"'):
        RuleLoader.compose_rules([a, a])
    with pytest.raises(RulesError, match="must contain a JSON object"):
        RuleLoader.compose_rules([write(tmp_path / "b.json", "[]")])
    with pytest.raises(RulesError, match="inertUnsafeFlags.rg must be an array"):
        RuleLoader.compose_rules([write(tmp_path / "d.json", {"inertUnsafeFlags": {"rg": "x"}})])
    with pytest.raises(RulesError, match="inertUnsafeFlags must be an object"):
        RuleLoader.compose_rules([write(tmp_path / "e.json", {"inertUnsafeFlags": []})])
    one = write(tmp_path / "f.json", {"extra": 1})
    with pytest.raises(RulesError, match="extra is set by more than one pack"):
        RuleLoader.compose_rules([one, one])
    arr = write(tmp_path / "g.json", {"extra": [1]})
    with pytest.raises(RulesError, match="extra must be an array"):
        RuleLoader.compose_rules([one, arr])


def test_compose_merges_in_first_seen_order(tmp_path):
    a = write(tmp_path / "a.json", {"inertPrograms": ["ls", "cat"], "inertUnsafeFlags": {"rg": ["--pre"]}, "runners": [["npx"]]})
    b = write(tmp_path / "b.json", {"inertPrograms": ["cat", "wc"], "inertUnsafeFlags": {"rg": ["--pre", "-z"], "fd": ["-x"]}, "runners": [["npx"]]})
    m = RuleLoader.compose_rules([a, b])
    assert m["inertPrograms"] == ["ls", "cat", "wc"]
    assert m["inertUnsafeFlags"] == {"rg": ["--pre", "-z"], "fd": ["-x"]}
    assert m["runners"] == [["npx"], ["npx"]]  # non-string lists are concatenated, not de-duplicated
