"""Rule loading and pack composition (destructive_guard.rules)."""

import json
import re

import pytest

from destructive_guard.rules import (
    DEFAULT_PACKS,
    PACKS_DIR,
    RulesError,
    compile_js_regex,
    compose_rules,
    load_packs,
    load_rules,
    pack_path,
    parse_rules,
)
from testkit.bridge import bridge

PACKS = sorted(p.stem for p in PACKS_DIR.glob("*.json"))


def to_json(value):
    """Rules with patterns as {"$regexp", "flags"}, the shape the JS bridge returns."""
    if isinstance(value, re.Pattern):
        return {"$regexp": value.pattern, "flags": "i" if value.flags & re.IGNORECASE else ""}
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_json(v) for v in value]
    return value


def normalize_js(value):
    """The JS bridge result with every {"$regexp"} compiled by the Python rules (same translation)."""
    if isinstance(value, dict):
        if set(value) == {"$regexp", "flags"}:
            # RegExp.source escapes `/`; the rule file did not
            return to_json(compile_js_regex(value["$regexp"].replace("\\/", "/"), value["flags"]))
        return {k: normalize_js(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_js(v) for v in value]
    return value


def write(path, obj):
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj))
    return path


def test_constants():
    assert DEFAULT_PACKS == ["base", "destructive"]
    assert pack_path("base") == str(PACKS_DIR / "base.json")
    assert PACKS == ["base", "destructive", "postgres", "terraform"]


def test_every_pack_regex_compiles():
    for name in PACKS:
        rules = load_packs([pack_path("base"), pack_path(name)] if name != "base" else [pack_path("base")])
        assert rules["rules"] or name == "base", name


@pytest.mark.parametrize("name", PACKS)
def test_parse_rules_matches_js_shape(name):
    path = pack_path(name)
    js = bridge("gate-engine", "loadRules", path)
    assert normalize_js(js) == to_json(load_rules(path))


def test_parse_rules_matches_js_shape_for_composed_packs():
    paths = [pack_path(n) for n in PACKS]
    assert normalize_js(bridge("gate-engine", "loadPacks", paths)) == to_json(load_packs(paths))


def test_compose_matches_js():
    paths = [pack_path(n) for n in ("base", "destructive", "postgres", "terraform")]
    assert compose_rules(paths) == bridge("gate-engine", "composeRules", paths)


def test_regex_translation():
    assert compile_js_regex(r"^a$").search("a\n") is None
    assert compile_js_regex(r"[$]").search("$")
    assert compile_js_regex(r"\$x").search("$x")
    assert compile_js_regex(r"(?<n>a)\1?").search("a")
    assert compile_js_regex("(?<!a)b").search("cb")
    assert compile_js_regex(r"\d").search("٣") is None  # JS \d is ASCII
    assert compile_js_regex("ab", "i").search("AB")


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
            load_rules(p)
    with pytest.raises(RulesError, match="cannot read rules file"):
        load_rules(tmp_path / "missing.json")
    with pytest.raises(RulesError, match="cannot read rules file"):
        write(p, '{"x": NaN}')
        load_rules(p)


def test_runners_legacy_forms_merge(tmp_path):
    p = write(
        tmp_path / "r.json",
        {"runners": [["npx"], ["pnpm", "exec"], {"program": "pnpm", "valueOptions": ["-C"]}, ["pnpm", "dlx"]]},
    )
    runners = {r["program"]: r for r in load_rules(p)["runners"]}
    assert runners["npx"] == {"program": "npx", "valueOptions": [], "subcommands": [], "shellOptions": [], "bareBin": True}
    assert runners["pnpm"]["subcommands"] == ["exec", "dlx"]
    assert runners["pnpm"]["valueOptions"] == ["-C"]


def test_parse_rules_defaults():
    parsed = parse_rules({"rules": [{"id": "g", "kind": "cli-gated"}, {"id": "m", "kind": "mcp-pattern", "toolWords": ["Drop"]}]})
    g, m = parsed["rules"]
    assert g["scriptScan"] is True
    assert g["dynamicArgs"] == "ask"
    assert g["whenArgs"] == []
    assert m["tool"].pattern == "^mcp__"
    assert m["toolWords"] == ["drop"]
    assert m["inputPattern"] is None
    assert parse_rules({}) == {
        "wrappers": [],
        "runners": [],
        "inertPrograms": [],
        "inertUnsafeFlags": {},
        "scriptPatterns": [],
        "scriptScanExempt": [],
        "rules": [],
    }


def test_when_args_follow_ignore_case():
    rule = parse_rules({"rules": [{"id": "g", "kind": "cli-gated", "whenArgs": ["^PROD"], "ignoreCase": True}]})["rules"][0]
    assert rule["whenArgs"][0].search("prod-1")
    rule = parse_rules({"rules": [{"id": "g", "kind": "cli-gated", "whenArgs": ["^PROD"]}]})["rules"][0]
    assert rule["whenArgs"][0].search("prod-1") is None


def test_compose_errors(tmp_path):
    a = write(tmp_path / "a.json", {"rules": [{"id": "x", "kind": "cli-gated", "programs": ["x"], "gatedPrefixes": [[]]}]})
    with pytest.raises(RulesError, match=r'a\.json: duplicate rule id "x"'):
        compose_rules([a, a])
    with pytest.raises(RulesError, match="must contain a JSON object"):
        compose_rules([write(tmp_path / "b.json", "[]")])
    with pytest.raises(RulesError, match="inertUnsafeFlags.rg must be an array"):
        compose_rules([write(tmp_path / "d.json", {"inertUnsafeFlags": {"rg": "x"}})])
    with pytest.raises(RulesError, match="inertUnsafeFlags must be an object"):
        compose_rules([write(tmp_path / "e.json", {"inertUnsafeFlags": []})])
    one = write(tmp_path / "f.json", {"extra": 1})
    with pytest.raises(RulesError, match="extra is set by more than one pack"):
        compose_rules([one, one])
    arr = write(tmp_path / "g.json", {"extra": [1]})
    with pytest.raises(RulesError, match="extra must be an array"):
        compose_rules([one, arr])


def test_compose_merges_in_first_seen_order(tmp_path):
    a = write(tmp_path / "a.json", {"inertPrograms": ["ls", "cat"], "inertUnsafeFlags": {"rg": ["--pre"]}, "runners": [["npx"]]})
    b = write(tmp_path / "b.json", {"inertPrograms": ["cat", "wc"], "inertUnsafeFlags": {"rg": ["--pre", "-z"], "fd": ["-x"]}, "runners": [["npx"]]})
    m = compose_rules([a, b])
    assert m["inertPrograms"] == ["ls", "cat", "wc"]
    assert m["inertUnsafeFlags"] == {"rg": ["--pre", "-z"], "fd": ["-x"]}
    assert m["runners"] == [["npx"], ["npx"]]  # non-string lists are concatenated, not de-duplicated
