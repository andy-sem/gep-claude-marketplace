"""Rule pack loading and composition."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from ..errors import RulesError

type Rules = dict[str, Any]


class RuleLoader:
    """Reads rule files and packs, composes them and hands them to the parser."""

    PACKS_DIR = Path(__file__).resolve().parents[3] / "packs"
    DEFAULT_PACKS: ClassVar[list[str]] = ["base", "destructive"]

    class _Unset:
        """A key that is absent (JS `undefined`), as opposed to `None` (JS `null`)."""

        def __repr__(self) -> str:
            return "UNSET"

    UNSET = _Unset()

    @classmethod
    def pack_path(cls, name: str) -> str:
        return str(cls.PACKS_DIR / f"{name}.json")

    @staticmethod
    def _reject_constant(name: str) -> Any:
        raise ValueError(f"Unexpected token {name} in JSON")

    @classmethod
    def _read_rules_json(cls, path: str | Path) -> Any:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=cls._reject_constant)
        except (OSError, ValueError) as e:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
            raise RulesError(f"cannot read rules file {path}: {e}") from None

    @classmethod
    def load_rules(cls, path: str | Path) -> Rules:
        from .rule_parser import (
            RuleParser,  # lazy: rule_parser imports this module for UNSET
        )

        return RuleParser.parse_rules(cls._read_rules_json(path))

    @classmethod
    def compose_rules(cls, paths: Sequence[str | Path]) -> dict[str, Any]:
        """Merge several raw rules files (packs) into one raw dict: string lists are concatenated
        without duplicates (first-seen order), runners/rules are concatenated, and inertUnsafeFlags
        lists are merged per program. Duplicate rule ids are an error."""
        merged: dict[str, Any] = {}
        ids: set[str] = set()
        for path in paths:
            raw = cls._read_rules_json(path)
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

    @classmethod
    def load_packs(cls, paths: Sequence[str | Path]) -> Rules:
        from .rule_parser import RuleParser  # lazy: see load_rules

        return RuleParser.parse_rules(cls.compose_rules(paths))
