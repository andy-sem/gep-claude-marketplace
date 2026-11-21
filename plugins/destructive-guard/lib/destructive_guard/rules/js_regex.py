"""JS regex source compiled to Python `re`."""

import json
import re
from typing import Any

from .rule_loader import RuleLoader


class JsRegex:
    """Compiles rule-file regexes written with JS semantics."""

    @staticmethod
    def _js_str(value: Any) -> str:
        """How a JS template literal prints a JSON value."""
        if value is RuleLoader.UNSET:
            return "undefined"
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return value
        return json.dumps(value)

    @staticmethod
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


    @classmethod
    def compile_js_regex(cls, source: str, flags: str = "") -> re.Pattern:
        """Compile a rule-file regex. ASCII classes (`\\d`, `\\w`, `\\b`) as in JS."""
        return re.compile(cls._translate(source), re.ASCII | (re.IGNORECASE if "i" in flags else 0))
