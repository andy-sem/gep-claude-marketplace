"""Evaluates one MCP tool call against the MCP rules."""

import re
from typing import Any

from ..rules.rule_loader import Rules
from ..shell.cmd import Cmd
from ..verdict import Verdict
from . import classifier
from .command_evaluator import CommandEvaluator


class McpEvaluator:
    """Evaluates MCP tool calls against one set of rules."""

    def __init__(self, rules: Rules) -> None:
        self.rules = rules

    def eval_mcp(self, rule: dict, tool_input: dict) -> dict | None:
        tool_name = tool_input["tool_name"]
        m = rule["tool"].search(tool_name)
        if not m:
            return None
        if rule["kind"] == "mcp-allowlist":
            suffix = (m.group(1) if m.re.groups >= 1 else None) or ""
            if any(rx.search(suffix) for rx in rule["readTools"]):
                return None
            return Verdict.ask(rule["id"], suffix)
        # mcp-as-cli
        args = classifier.Classifier._member(tool_input.get("tool_input"), rule["argsField"])
        if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
            return Verdict.ask("unparsable", f'{tool_name} is missing a string array "{rule["argsField"]}"')
        lst = args[1:] if args and Cmd.basename(args[0]) == rule["program"] else args
        return CommandEvaluator(
            {**self.rules, "rules": [r for r in self.rules["rules"] if classifier.Classifier.is_cli_rule(r)]}
        ).eval_tokens([rule["program"], *lst], 0)

    _TOOL_WORD_SPLIT = re.compile(r"[_\-\s]+|(?<=[a-z0-9])(?=[A-Z])")

    @classmethod
    def tool_words(cls, tool_name: str) -> list[str]:
        """Words of an MCP tool name after its last `__`: split on `_`, `-` and camelCase."""
        suffix = tool_name[tool_name.rfind("__") + 2 :]
        return [w.lower() for w in cls._TOOL_WORD_SPLIT.split(suffix) if w]

    @staticmethod
    def input_strings(value: Any, out: list[str] | None = None, depth: int = 0) -> list[str]:
        """Every string inside an MCP input (bounded depth)."""
        out = [] if out is None else out
        if depth > 8:
            return out
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            for v in value:
                McpEvaluator.input_strings(v, out, depth + 1)
        elif isinstance(value, dict):
            for v in value.values():
                McpEvaluator.input_strings(v, out, depth + 1)
        return out

    @classmethod
    def eval_mcp_pattern(cls, rule: dict, tool_input: dict) -> dict | None:
        name = tool_input["tool_name"]
        if not rule["tool"].search(name):
            return None
        words = cls.tool_words(name)
        if rule["toolWords"] and not any(w in rule["toolWords"] for w in words):
            return None
        if rule["inputPattern"]:
            hit = any(rule["inputPattern"].search(t) for t in cls.input_strings(tool_input.get("tool_input")))
            if not hit:
                return None
        return Verdict.ask(rule["id"], name[name.rfind("__") + 2 :])
