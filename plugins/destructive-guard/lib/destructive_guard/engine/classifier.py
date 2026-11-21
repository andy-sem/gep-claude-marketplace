"""Rule decision for one hook input."""

from typing import Any

from ..errors import UnparsableError
from ..rules.rule_loader import Rules
from ..shell.tokenizer import ShellTokenizer
from ..verdict import Verdict
from . import mcp_evaluator
from .command_evaluator import CommandEvaluator


class Classifier:
    """Classifies hook inputs against one set of rules."""

    def __init__(self, rules: Rules, strict: bool = True) -> None:
        self.rules = rules
        self.strict = strict

    @staticmethod
    def is_cli_rule(rule: dict) -> bool:
        return rule["kind"] in ("cli-allowlist", "cli-gated")

    @staticmethod
    def _member(obj: Any, key: str) -> Any:
        """JS `obj?.[key]`: a missing key, or an obj that is not an object, gives None."""
        return obj.get(key) if isinstance(obj, dict) else None

    def classify(self, input: Any) -> dict | None:
        """The rule decision for one hook input: an `ask` result or None. With `strict=False` a Bash
        command (or part of one) the parser cannot read gives no opinion instead of an `unparsable` ask;
        the other parts are still checked. Input-level problems (no tool name, no command) always ask."""
        try:
            return self._classify_inner(input)
        except UnparsableError as e:
            return Verdict.ask("unparsable", str(e))
        except Exception as e:  # noqa: BLE001 (fail closed on any engine bug)
            return Verdict.ask("unparsable", f"internal error: {e}")

    def _classify_inner(self, input: Any) -> dict | None:
        if not isinstance(input, dict):
            return Verdict.ask("unparsable", "hook input is not an object")
        tool_name = input.get("tool_name")
        if not isinstance(tool_name, str):
            return Verdict.ask("unparsable", "hook input has no tool_name")

        if tool_name == "Bash":
            command = Classifier._member(input.get("tool_input"), "command")
            if not isinstance(command, str):
                return Verdict.ask("unparsable", "Bash call has no command")
            loose = not self.strict
            if loose:
                try:
                    parts = ShellTokenizer.split_command(command, loose=True)
                except UnparsableError:
                    return None
                for tokens in parts:
                    try:
                        r = CommandEvaluator(self.rules).eval_tokens(tokens, 0, True)
                        if r:
                            return r
                    except UnparsableError:
                        pass
                return None
            try:
                for tokens in ShellTokenizer.split_command(command):
                    r = CommandEvaluator(self.rules).eval_tokens(tokens, 0)
                    if r:
                        return r
            except UnparsableError as e:
                # The command string itself could not be parsed. Marked so the optional Jev layer may
                # judge it; input-level failures stay closed.
                return {**Verdict.ask("unparsable", str(e)), "commandUnparsable": True}
            return None

        for rule in self.rules["rules"]:
            r = None
            if rule["kind"] == "mcp-pattern":
                r = mcp_evaluator.McpEvaluator.eval_mcp_pattern(rule, input)
            elif rule["kind"] in ("mcp-allowlist", "mcp-as-cli"):
                r = mcp_evaluator.McpEvaluator(self.rules).eval_mcp(rule, input)
            if r:
                return r
        return None
