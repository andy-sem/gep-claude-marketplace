"""Tool-agnostic approval gate engine (port of the parser and rule evaluation of gate-engine.mjs).

Reads rules from JSON rule packs (see `rules`); this module knows no concrete tool names.
Fails closed: anything it cannot parse results in an `ask`. `Classifier.classify` is the rule decision for
one hook input; `gate` adds the script scan and the optional Jev layer.

The shell tokenizer is hand-written on purpose (no `shlex`): the gate has to see through
substitutions, heredocs and nested shells the way the JS did. The JS module-level flags
(`loose`, `currentScope`) are explicit parameters here.
"""

import os
from collections.abc import Mapping
from typing import Any

from .engine.classifier import Classifier
from .rules.rule_loader import Rules
from .verdict import Verdict

__all__ = [
    "Rules",
    "gate",
]


# ---------------------------------------------------------------------------
# gate: rules + script scan + optional Jev
# ---------------------------------------------------------------------------


def _closed(result: dict | None) -> bool:
    """Results the script scan and Jev never touch: config errors and input-level unparsable asks."""
    if not result:
        return False
    reason = result["reason"]
    return reason.startswith("gate-config:") or (reason.startswith("unparsable:") and not result.get("commandUnparsable"))


def apply_jev(input: Any, result: dict | None, rules: Rules, collected: dict | None, env: Mapping[str, str]) -> dict | None:
    """The optional Jev layer (gate_jev, imported only when GATE_JEV is set so the output is unchanged
    without it). Whatever the rules said stays the answer when Jev fails or is unsure; a missing or
    invalid Jev variable asks."""
    if not env.get("GATE_JEV"):
        return result
    if _closed(result):
        return result
    try:
        from . import gate_jev

        cfg = gate_jev.read_jev_config(env)
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
        return gate_jev.run_jev(call, result, cfg)
    except Exception:  # noqa: BLE001
        return result


def gate(
    input: Any,
    rules: Rules,
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
    strict: bool = True,
    trace: dict | None = None,
) -> dict | None:
    """The full decision for one hook input: the rule result, the script scan as a fallback for Bash
    calls no rule matched (also run for Jev when GATE_JEV is set), then the optional Jev layer. Returns
    an `ask` result or None (no output). `trace`, when given, receives the result before Jev as
    `trace["rule"]` (for GATE_LOG)."""
    if env is None:
        env = os.environ
    result = Classifier(rules, strict).classify(input)
    collected = None
    command = Classifier._member(Classifier._member(input, "tool_input"), "command")
    if (
        Classifier._member(input, "tool_name") == "Bash"
        and isinstance(command, str)
        and not _closed(result)
        and (not result or env.get("GATE_JEV"))
    ):
        try:
            from . import gate_scripts

            where = input["cwd"] if isinstance(input.get("cwd"), str) else (cwd if cwd is not None else os.getcwd())
            collected = gate_scripts.collect_scripts(
                command, rules, cwd=where, root=gate_scripts.find_project_root(where, env)
            )
            if not result:
                result = gate_scripts.scan_scripts(collected, rules)
        except Exception as e:  # noqa: BLE001
            return Verdict.ask("gate-config", f"script scan failed: {e}")
    if trace is not None:
        trace["rule"] = result
    return apply_jev(input, result, rules, collected, env)
