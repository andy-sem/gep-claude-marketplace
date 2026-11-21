"""Tool-agnostic approval gate: rules + script scan + optional Jev.

Reads rules from JSON rule packs (see `rules`); knows no concrete tool names.
Fails closed: anything it cannot parse results in an `ask`. `Classifier.classify` is the rule decision for
one hook input; `Gate.gate` adds the script scan and the optional Jev layer.
"""

import os
from collections.abc import Callable, Mapping
from typing import Any

from ..engine.classifier import Classifier
from ..rules.rule_loader import Rules
from ..verdict import Verdict


class Gate:
    """The full decision for one hook input: rules, script scan, optional Jev."""

    def __init__(
        self,
        rules: Rules,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        collect_scripts: Callable[[str, str, str], dict[str, Any]] | None = None,
    ) -> None:
        """`collect_scripts(command, cwd, root)` defaults to `ScriptCollector(rules, cwd, root).collect(command)`
        (imported lazily, only when a scan runs)."""
        self.rules = rules
        self.env = os.environ if env is None else env
        self.cwd = cwd
        self.collect_scripts = collect_scripts

    @staticmethod
    def _closed(result: dict | None) -> bool:
        """Results the script scan and Jev never touch: config errors and input-level unparsable asks."""
        if not result:
            return False
        reason = result["reason"]
        return reason.startswith("gate-config:") or (reason.startswith("unparsable:") and not result.get("commandUnparsable"))

    def apply_jev(self, input: Any, result: dict | None, collected: dict | None) -> dict | None:
        """The optional Jev layer (JevDecider, imported only when GATE_JEV is set so the output is unchanged
        without it). Whatever the rules said stays the answer when Jev fails or is unsure; a missing or
        invalid Jev variable asks."""
        if not self.env.get("GATE_JEV"):
            return result
        if Gate._closed(result):
            return result
        try:
            from ..jev.config import JevConfig
            from ..jev.decider import JevDecider

            cfg = JevConfig.read(self.env)
        except Exception as e:  # noqa: BLE001 - any failure here is a config problem: ask
            return Verdict.ask("gate-config", str(e))
        if not cfg:
            return result
        tool = Classifier._member(input, "tool_name")
        if tool == "Bash":
            call: dict[str, Any] = {
                "tool": tool,
                "command": input["tool_input"]["command"],
                "scripts": (collected or {}).get("files") or [],
                "problems": (collected or {}).get("problems") or [],
            }
        elif isinstance(tool, str) and tool.startswith("mcp__"):
            tool_input = input.get("tool_input")
            call = {"tool": tool, "input": tool_input if tool_input is not None else {}}
        else:
            return result
        # GATE_JEV_SCOPE: calls of a kind left out keep the rule result, no request.
        scope = cfg.get("scope")
        if scope and ("bash" if tool == "Bash" else "mcp") not in scope:
            return result
        try:
            return JevDecider.run_jev(call, result, cfg)
        except Exception:  # noqa: BLE001
            return result

    def gate(
        self,
        input: Any,
        *,
        strict: bool = True,
        trace: dict | None = None,
    ) -> dict | None:
        """The full decision for one hook input: the rule result, the script scan as a fallback for Bash
        calls no rule matched (also run for Jev when GATE_JEV is set), then the optional Jev layer. Returns
        an `ask` result or None (no output). `trace`, when given, receives the result before Jev as
        `trace["rule"]` (for GATE_LOG)."""
        result = Classifier(self.rules, strict).classify(input)
        collected = None
        command = Classifier._member(Classifier._member(input, "tool_input"), "command")
        if (
            Classifier._member(input, "tool_name") == "Bash"
            and isinstance(command, str)
            and not Gate._closed(result)
            and (not result or self.env.get("GATE_JEV"))
        ):
            try:
                from ..scripts.project_paths import ProjectPaths
                from ..scripts.script_collector import ScriptCollector
                from ..scripts.script_scanner import ScriptScanner

                where = input["cwd"] if isinstance(input.get("cwd"), str) else (self.cwd if self.cwd is not None else os.getcwd())
                root = ProjectPaths.find_project_root(where, self.env)
                if self.collect_scripts is not None:
                    collected = self.collect_scripts(command, where, root)
                else:
                    collected = ScriptCollector(self.rules, where, root).collect(command)
                if not result:
                    result = ScriptScanner(self.rules).scan_scripts(collected)
            except Exception as e:  # noqa: BLE001
                return Verdict.ask("gate-config", f"script scan failed: {e}")
        if trace is not None:
            trace["rule"] = result
        return self.apply_jev(input, result, collected)
