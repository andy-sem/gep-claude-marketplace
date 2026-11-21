"""Rule file parsing and validation."""

import re
from typing import Any

from ..errors import RulesError
from .js_regex import JsRegex
from .rule_loader import RuleLoader, Rules


class RuleParser:
    """Validates raw rule dicts (JS key spelling) and compiles their regexes."""

    KNOWN_KINDS = ("cli-allowlist", "cli-gated", "mcp-allowlist", "mcp-as-cli", "mcp-pattern")

    @staticmethod
    def _regex(source: Any, what: str, flags: str = "") -> re.Pattern:
        if not isinstance(source, str):
            raise RulesError(f"{what} must be a regex string")
        try:
            return JsRegex.compile_js_regex(source, flags)
        except re.error as e:
            raise RulesError(f"{what} is not a valid regex: {e}") from None

    @staticmethod
    def _str_array(value: Any, what: str) -> list[str]:
        if value is RuleLoader.UNSET:
            return []
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            raise RulesError(f"{what} must be an array of strings")
        return value

    @classmethod
    def _non_empty_str_array(cls, value: Any, what: str) -> list[str]:
        items = cls._str_array(value, what)
        if any(v == "" for v in items):
            raise RulesError(f"{what} must not contain empty strings")
        return items

    @staticmethod
    def _str_array_array(value: Any, what: str) -> list[list[str]]:
        if value is RuleLoader.UNSET:
            return []
        if not isinstance(value, list) or any(
            not isinstance(v, list) or any(not isinstance(s, str) for s in v) for v in value
        ):
            raise RulesError(f"{what} must be an array of string arrays")
        return value

    @staticmethod
    def _flag_map(value: Any, what: str) -> dict[str, list[str]]:
        if value is RuleLoader.UNSET:
            return {}
        if not isinstance(value, dict):
            raise RulesError(f"{what} must be an object of string arrays")
        out = {}
        for program, flags in value.items():
            if not isinstance(flags, list) or any(not isinstance(f, str) or f == "" for f in flags):
                raise RulesError(f"{what} {program} must be an array of non-empty strings")
            out[program] = flags
        return out

    @staticmethod
    def _bool(value: Any, what: str) -> bool:
        if value is RuleLoader.UNSET:
            return False
        if not isinstance(value, bool):
            raise RulesError(f"{what} must be a boolean")
        return value

    @classmethod
    def _runner_list(cls, value: Any) -> list[dict[str, Any]]:
        """Runners run another program. The legacy form `["pnpm", "exec"]` / `["npx"]` is also accepted."""
        if value is RuleLoader.UNSET:
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
            r["valueOptions"].extend(cls._str_array(raw.get("valueOptions", RuleLoader.UNSET), f"{where} valueOptions"))
            r["subcommands"].extend(cls._str_array(raw.get("subcommands", RuleLoader.UNSET), f"{where} subcommands"))
            r["shellOptions"].extend(cls._str_array(raw.get("shellOptions", RuleLoader.UNSET), f"{where} shellOptions"))
            r["bareBin"] = cls._bool(raw.get("bareBin", RuleLoader.UNSET), f"{where} bareBin") or r["bareBin"]
        return list(by_program.values())

    @classmethod
    def _parse_rule(cls, raw: Any, index: int) -> dict[str, Any]:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            raise RulesError(f"rule #{index} needs a string id")
        where = f'rule "{raw["id"]}"'
        kind = raw.get("kind", RuleLoader.UNSET)
        if not (isinstance(kind, str) and kind in cls.KNOWN_KINDS):
            raise RulesError(f'{where} has unknown kind "{JsRegex._js_str(kind)}"')

        def get(key: str) -> Any:
            return raw.get(key, RuleLoader.UNSET)

        rule: dict[str, Any] = {"id": raw["id"], "kind": kind}
        if kind == "cli-allowlist":
            rule["programs"] = cls._str_array(get("programs"), f"{where} programs")
            rule["skipWords"] = cls._str_array(get("skipWords"), f"{where} skipWords")
            rule["readPrefixes"] = cls._str_array_array(get("readPrefixes"), f"{where} readPrefixes")
            rule["readSequences"] = cls._str_array_array(get("readSequences"), f"{where} readSequences")
            rule["readVerbs"] = cls._str_array(get("readVerbs"), f"{where} readVerbs")
            rule["writeVerbs"] = cls._str_array(get("writeVerbs"), f"{where} writeVerbs")
            rule["helpFlags"] = cls._str_array(get("helpFlags"), f"{where} helpFlags")
            rule["helpWords"] = cls._str_array(get("helpWords"), f"{where} helpWords")
            rule["scriptScan"] = True if get("scriptScan") is RuleLoader.UNSET else cls._bool(get("scriptScan"), f"{where} scriptScan")
        elif kind == "cli-gated":
            rule["programs"] = cls._str_array(get("programs"), f"{where} programs")
            rule["gatedPrefixes"] = cls._str_array_array(get("gatedPrefixes"), f"{where} gatedPrefixes")
            rule["unlessFlags"] = cls._str_array(get("unlessFlags"), f"{where} unlessFlags")
            rule["helpFlags"] = cls._str_array(get("helpFlags"), f"{where} helpFlags")
            rule["helpWords"] = cls._str_array(get("helpWords"), f"{where} helpWords")
            rule["whenFlags"] = cls._str_array_array(get("whenFlags"), f"{where} whenFlags")
            if any(not g or any(not f for f in g) for g in rule["whenFlags"]):
                raise RulesError(f"{where} whenFlags groups must be non-empty")
            rule["ignoreCase"] = cls._bool(get("ignoreCase"), f"{where} ignoreCase")
            rule["whenArgs"] = [
                cls._regex(r, f"{where} whenArgs entry", "i" if rule["ignoreCase"] else "")
                for r in cls._str_array(get("whenArgs"), f"{where} whenArgs")
            ]
            rule["shortBundles"] = cls._bool(get("shortBundles"), f"{where} shortBundles")
            rule["matchStdin"] = cls._bool(get("matchStdin"), f"{where} matchStdin")
            dynamic = get("dynamicArgs")
            if dynamic is not RuleLoader.UNSET and dynamic not in ("ask", "ignore"):
                raise RulesError(f'{where} dynamicArgs must be "ask" or "ignore"')
            rule["dynamicArgs"] = "ask" if dynamic is RuleLoader.UNSET else dynamic
            rule["scriptScan"] = True if get("scriptScan") is RuleLoader.UNSET else cls._bool(get("scriptScan"), f"{where} scriptScan")
        elif kind == "mcp-pattern":
            tool = raw.get("tool")
            rule["tool"] = cls._regex("^mcp__" if tool is None else tool, f"{where} tool")
            rule["toolWords"] = [
                w.lower() for w in cls._non_empty_str_array(get("toolWords"), f"{where} toolWords")
            ]
            rule["inputPattern"] = (
                None if get("inputPattern") is RuleLoader.UNSET else cls._regex(get("inputPattern"), f"{where} inputPattern", "i")
            )
            if not rule["toolWords"] and not rule["inputPattern"] and get("tool") is RuleLoader.UNSET:
                raise RulesError(f"{where} needs tool, toolWords or inputPattern")
        elif kind == "mcp-allowlist":
            rule["tool"] = cls._regex(get("tool"), f"{where} tool")
            rule["readTools"] = [
                cls._regex(r, f"{where} readTools entry") for r in cls._str_array(get("readTools"), f"{where} readTools")
            ]
        elif kind == "mcp-as-cli":
            rule["tool"] = cls._regex(get("tool"), f"{where} tool")
            if not isinstance(get("argsField"), str) or not isinstance(get("program"), str):
                raise RulesError(f"{where} needs string argsField and program")
            rule["argsField"] = raw["argsField"]
            rule["program"] = raw["program"]
        return rule

    @classmethod
    def parse_rules(cls, parsed: Any) -> Rules:
        if not isinstance(parsed, dict):
            raise RulesError("rules file must contain a JSON object")
        raw_rules = parsed.get("rules", RuleLoader.UNSET)
        if raw_rules is not RuleLoader.UNSET and not isinstance(raw_rules, list):
            raise RulesError("rules must be an array")
        rules = [cls._parse_rule(raw, index) for index, raw in enumerate([] if raw_rules is RuleLoader.UNSET else raw_rules)]

        def get(key: str) -> Any:
            return parsed.get(key, RuleLoader.UNSET)

        return {
            "wrappers": cls._str_array(get("wrappers"), "wrappers"),
            "runners": cls._runner_list(get("runners")),
            "inertPrograms": cls._str_array(get("inertPrograms"), "inertPrograms"),
            "inertUnsafeFlags": cls._flag_map(get("inertUnsafeFlags"), "inertUnsafeFlags"),
            "scriptPatterns": [
                cls._regex(source, "scriptPatterns entry") for source in cls._str_array(get("scriptPatterns"), "scriptPatterns")
            ],
            "scriptScanExempt": cls._non_empty_str_array(get("scriptScanExempt"), "scriptScanExempt"),
            "rules": rules,
        }
