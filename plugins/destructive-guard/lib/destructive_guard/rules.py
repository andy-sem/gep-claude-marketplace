"""Rule pack loading and composition (the "Rules loading" part of gate-engine.mjs).

Rules are dicts with the JS key spelling; regex fields are compiled `re.Pattern`s.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"
DEFAULT_PACKS = ["base", "destructive"]

KNOWN_KINDS = ("cli-allowlist", "cli-gated", "mcp-allowlist", "mcp-as-cli", "mcp-pattern")

Rules = dict[str, Any]


class RulesError(Exception):
    pass


class _Unset:
    """A key that is absent (JS `undefined`), as opposed to `None` (JS `null`)."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


def pack_path(name: str) -> str:
    return str(PACKS_DIR / f"{name}.json")


def _js_str(value: Any) -> str:
    """How a JS template literal prints a JSON value."""
    if value is UNSET:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return json.dumps(value)


# --- regex (JS source -> re) --------------------------------------------------


def _translate(source: str) -> str:
    """JS regex source to `re` source: `$` means end of input (not before a final newline),
    and `(?<name>` is a named group."""
    out: list[str] = []
    in_class = False
    i = 0
    n = len(source)
    while i < n:
        c = source[i]
        if c == "\\" and i + 1 < n:
            out.append(source[i : i + 2])
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
            out.append(c)
        elif c == "[":
            in_class = True
            out.append(c)
        elif c == "$":
            out.append(r"\Z")
        elif source.startswith("(?<", i) and i + 3 < n and source[i + 3] not in "=!":
            out.append("(?P<")
            i += 3
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def compile_js_regex(source: str, flags: str = "") -> re.Pattern:
    """Compile a rule-file regex. ASCII classes (`\\d`, `\\w`, `\\b`) as in JS."""
    return re.compile(_translate(source), re.ASCII | (re.IGNORECASE if "i" in flags else 0))


def _regex(source: Any, what: str, flags: str = "") -> re.Pattern:
    if not isinstance(source, str):
        raise RulesError(f"{what} must be a regex string")
    try:
        return compile_js_regex(source, flags)
    except re.error as e:
        raise RulesError(f"{what} is not a valid regex: {e}") from None


# --- validators -----------------------------------------------------------------


def _str_array(value: Any, what: str) -> list[str]:
    if value is UNSET:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise RulesError(f"{what} must be an array of strings")
    return value


def _non_empty_str_array(value: Any, what: str) -> list[str]:
    items = _str_array(value, what)
    if any(v == "" for v in items):
        raise RulesError(f"{what} must not contain empty strings")
    return items


def _str_array_array(value: Any, what: str) -> list[list[str]]:
    if value is UNSET:
        return []
    if not isinstance(value, list) or any(
        not isinstance(v, list) or any(not isinstance(s, str) for s in v) for v in value
    ):
        raise RulesError(f"{what} must be an array of string arrays")
    return value


def _flag_map(value: Any, what: str) -> dict[str, list[str]]:
    if value is UNSET:
        return {}
    if not isinstance(value, dict):
        raise RulesError(f"{what} must be an object of string arrays")
    out = {}
    for program, flags in value.items():
        if not isinstance(flags, list) or any(not isinstance(f, str) or f == "" for f in flags):
            raise RulesError(f"{what} {program} must be an array of non-empty strings")
        out[program] = flags
    return out


def _bool(value: Any, what: str) -> bool:
    if value is UNSET:
        return False
    if not isinstance(value, bool):
        raise RulesError(f"{what} must be a boolean")
    return value


def _runner_list(value: Any) -> list[dict[str, Any]]:
    """Runners run another program. The legacy form `["pnpm", "exec"]` / `["npx"]` is also accepted."""
    if value is UNSET:
        return []
    if not isinstance(value, list):
        raise RulesError("runners must be an array")
    by_program: dict[str, dict[str, Any]] = {}

    def entry(program: str) -> dict[str, Any]:
        if program not in by_program:
            by_program[program] = {
                "program": program,
                "valueOptions": [],
                "subcommands": [],
                "shellOptions": [],
                "bareBin": False,
            }
        return by_program[program]

    for index, raw in enumerate(value):
        where = f"runner #{index}"
        if isinstance(raw, list):
            if len(raw) < 1 or len(raw) > 2 or any(not isinstance(v, str) or not v for v in raw):
                raise RulesError(f'{where} must be ["program"] or ["program", "sub"]')
            r = entry(raw[0])
            if len(raw) == 1:
                r["bareBin"] = True
            else:
                r["subcommands"].append(raw[1])
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("program"), str) or not raw["program"]:
            raise RulesError(f"{where} needs a string program")
        r = entry(raw["program"])
        r["valueOptions"].extend(_str_array(raw.get("valueOptions", UNSET), f"{where} valueOptions"))
        r["subcommands"].extend(_str_array(raw.get("subcommands", UNSET), f"{where} subcommands"))
        r["shellOptions"].extend(_str_array(raw.get("shellOptions", UNSET), f"{where} shellOptions"))
        r["bareBin"] = _bool(raw.get("bareBin", UNSET), f"{where} bareBin") or r["bareBin"]
    return list(by_program.values())


# --- loading ----------------------------------------------------------------------


def _reject_constant(name: str) -> Any:
    raise ValueError(f"Unexpected token {name} in JSON")


def _read_rules_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (OSError, ValueError) as e:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        raise RulesError(f"cannot read rules file {path}: {e}") from None


def load_rules(path: str | Path) -> Rules:
    return parse_rules(_read_rules_json(path))


def compose_rules(paths: Sequence[str | Path]) -> dict[str, Any]:
    """Merge several raw rules files (packs) into one raw dict: string lists are concatenated
    without duplicates (first-seen order), runners/rules are concatenated, and inertUnsafeFlags
    lists are merged per program. Duplicate rule ids are an error."""
    merged: dict[str, Any] = {}
    ids: set[str] = set()
    for path in paths:
        raw = _read_rules_json(path)
        if not isinstance(raw, dict):
            raise RulesError(f"rules file {path} must contain a JSON object")
        for key, value in raw.items():
            if key == "inertUnsafeFlags":
                if not isinstance(value, dict):
                    raise RulesError(f"{path}: inertUnsafeFlags must be an object")
                if merged.get(key) is None:
                    merged[key] = {}
                into = merged[key]
                for prog, flags in value.items():
                    if not isinstance(flags, list):
                        raise RulesError(f"{path}: inertUnsafeFlags.{prog} must be an array")
                    into[prog] = list(dict.fromkeys([*into.get(prog, []), *flags]))
            elif isinstance(value, list):
                if key == "rules":
                    for r in value:
                        if isinstance(r, dict) and isinstance(r.get("id"), str):
                            if r["id"] in ids:
                                raise RulesError(f'{path}: duplicate rule id "{r["id"]}"')
                            ids.add(r["id"])
                prev = merged.get(key)
                if prev is None:
                    prev = []
                if not isinstance(prev, list):
                    raise RulesError(f"{path}: {key} must be an array")
                if all(isinstance(v, str) for v in value):
                    merged[key] = list(dict.fromkeys([*prev, *value]))
                else:
                    merged[key] = [*prev, *value]
            elif key not in merged:
                merged[key] = value
            else:
                raise RulesError(f"{path}: {key} is set by more than one pack")
    return merged


def load_packs(paths: Sequence[str | Path]) -> Rules:
    return parse_rules(compose_rules(paths))


def _parse_rule(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
        raise RulesError(f"rule #{index} needs a string id")
    where = f'rule "{raw["id"]}"'
    kind = raw.get("kind", UNSET)
    if not (isinstance(kind, str) and kind in KNOWN_KINDS):
        raise RulesError(f'{where} has unknown kind "{_js_str(kind)}"')

    def get(key: str) -> Any:
        return raw.get(key, UNSET)

    rule: dict[str, Any] = {"id": raw["id"], "kind": kind}
    if kind == "cli-allowlist":
        rule["programs"] = _str_array(get("programs"), f"{where} programs")
        rule["skipWords"] = _str_array(get("skipWords"), f"{where} skipWords")
        rule["readPrefixes"] = _str_array_array(get("readPrefixes"), f"{where} readPrefixes")
        rule["readSequences"] = _str_array_array(get("readSequences"), f"{where} readSequences")
        rule["readVerbs"] = _str_array(get("readVerbs"), f"{where} readVerbs")
        rule["writeVerbs"] = _str_array(get("writeVerbs"), f"{where} writeVerbs")
        rule["helpFlags"] = _str_array(get("helpFlags"), f"{where} helpFlags")
        rule["helpWords"] = _str_array(get("helpWords"), f"{where} helpWords")
        rule["scriptScan"] = True if get("scriptScan") is UNSET else _bool(get("scriptScan"), f"{where} scriptScan")
    elif kind == "cli-gated":
        rule["programs"] = _str_array(get("programs"), f"{where} programs")
        rule["gatedPrefixes"] = _str_array_array(get("gatedPrefixes"), f"{where} gatedPrefixes")
        rule["unlessFlags"] = _str_array(get("unlessFlags"), f"{where} unlessFlags")
        rule["helpFlags"] = _str_array(get("helpFlags"), f"{where} helpFlags")
        rule["helpWords"] = _str_array(get("helpWords"), f"{where} helpWords")
        rule["whenFlags"] = _str_array_array(get("whenFlags"), f"{where} whenFlags")
        if any(not g or any(not f for f in g) for g in rule["whenFlags"]):
            raise RulesError(f"{where} whenFlags groups must be non-empty")
        rule["ignoreCase"] = _bool(get("ignoreCase"), f"{where} ignoreCase")
        rule["whenArgs"] = [
            _regex(r, f"{where} whenArgs entry", "i" if rule["ignoreCase"] else "")
            for r in _str_array(get("whenArgs"), f"{where} whenArgs")
        ]
        rule["shortBundles"] = _bool(get("shortBundles"), f"{where} shortBundles")
        rule["matchStdin"] = _bool(get("matchStdin"), f"{where} matchStdin")
        dynamic = get("dynamicArgs")
        if dynamic is not UNSET and dynamic not in ("ask", "ignore"):
            raise RulesError(f'{where} dynamicArgs must be "ask" or "ignore"')
        rule["dynamicArgs"] = "ask" if dynamic is UNSET else dynamic
        rule["scriptScan"] = True if get("scriptScan") is UNSET else _bool(get("scriptScan"), f"{where} scriptScan")
    elif kind == "mcp-pattern":
        tool = raw.get("tool")
        rule["tool"] = _regex("^mcp__" if tool is None else tool, f"{where} tool")
        rule["toolWords"] = [
            w.lower() for w in _non_empty_str_array(get("toolWords"), f"{where} toolWords")
        ]
        rule["inputPattern"] = (
            None if get("inputPattern") is UNSET else _regex(get("inputPattern"), f"{where} inputPattern", "i")
        )
        if not rule["toolWords"] and not rule["inputPattern"] and get("tool") is UNSET:
            raise RulesError(f"{where} needs tool, toolWords or inputPattern")
    elif kind == "mcp-allowlist":
        rule["tool"] = _regex(get("tool"), f"{where} tool")
        rule["readTools"] = [
            _regex(r, f"{where} readTools entry") for r in _str_array(get("readTools"), f"{where} readTools")
        ]
    elif kind == "mcp-as-cli":
        rule["tool"] = _regex(get("tool"), f"{where} tool")
        if not isinstance(get("argsField"), str) or not isinstance(get("program"), str):
            raise RulesError(f"{where} needs string argsField and program")
        rule["argsField"] = raw["argsField"]
        rule["program"] = raw["program"]
    return rule


def parse_rules(parsed: Any) -> Rules:
    if not isinstance(parsed, dict):
        raise RulesError("rules file must contain a JSON object")
    raw_rules = parsed.get("rules", UNSET)
    if raw_rules is not UNSET and not isinstance(raw_rules, list):
        raise RulesError("rules must be an array")
    rules = [_parse_rule(raw, index) for index, raw in enumerate([] if raw_rules is UNSET else raw_rules)]

    def get(key: str) -> Any:
        return parsed.get(key, UNSET)

    return {
        "wrappers": _str_array(get("wrappers"), "wrappers"),
        "runners": _runner_list(get("runners")),
        "inertPrograms": _str_array(get("inertPrograms"), "inertPrograms"),
        "inertUnsafeFlags": _flag_map(get("inertUnsafeFlags"), "inertUnsafeFlags"),
        "scriptPatterns": [
            _regex(source, "scriptPatterns entry") for source in _str_array(get("scriptPatterns"), "scriptPatterns")
        ],
        "scriptScanExempt": _non_empty_str_array(get("scriptScanExempt"), "scriptScanExempt"),
        "rules": rules,
    }
