"""Hook entry: stdin JSON -> decision on stdout (port of main/emit/logDecision of gate-engine.mjs).

Fails closed: any exception becomes a `gate-config: internal error` ask. The done-file
(`GATE_DONE_FILE`) is written only after the decision is on stdout; the wrapper allows only when
it exists. `GATE_ENABLED=0` emits nothing and does not read stdin.
"""

import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, BinaryIO

from .errors import RulesError
from .gate.gate import Gate
from .verdict import Verdict


class GateHook:
    """Reads one hook input from stdin, decides it and writes the decision to stdout."""

    @staticmethod
    def _reject_constant(name: str) -> Any:
        # JSON.parse refuses NaN and Infinity; Python's json accepts them by default.
        raise ValueError(f"invalid JSON constant {name}")

    @staticmethod
    def emit(result: dict) -> None:
        text = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": result["decision"],
                    "permissionDecisionReason": result["reason"],
                }
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        out = sys.stdout.buffer
        out.write(text.encode("utf-8", errors="replace"))
        out.flush()

    @staticmethod
    def log_decision(path: str, input: Any, rule: dict | None, result: dict | None) -> None:
        """GATE_LOG: one JSON line per decision. Commands are redacted like Jev input; a command that
        mentions .env is not written. Never fails the gate."""
        try:
            tool = input.get("tool_name") if isinstance(input, dict) else None
            if not isinstance(tool, str):
                tool = None
            record: dict[str, Any] = {"ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", "tool": tool}
            tool_input = input.get("tool_input") if isinstance(input, dict) else None
            command = tool_input.get("command") if isinstance(tool_input, dict) else None
            if tool == "Bash" and isinstance(command, str):
                from .jev.redactor import Redactor

                record["command"] = Redactor.redact(command)
            record["rule"] = rule["reason"] if rule else None
            record["decision"] = result["decision"] if result else "none"
            record["reason"] = result["reason"] if result else None
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            with open(path, "a", encoding="utf-8", errors="replace") as f:
                f.write(line + "\n")
        except Exception:  # noqa: BLE001, S110 - the log is best-effort
            pass

    @classmethod
    def main(cls, stdin: BinaryIO | None = None, env: Mapping[str, str] | None = None) -> int:
        if stdin is None:
            stdin = sys.stdin.buffer
        if env is None:
            env = os.environ
        result: dict | None = None
        config: dict | None = None
        input: Any = None
        trace: dict = {}
        try:
            rules = None
            try:
                from .config import GateConfig
                from .errors import ConfigError

                try:
                    config = GateConfig.read_config(env)
                    if config["enabled"]:
                        rules = GateConfig.build_rules(config)
                except (RulesError, ConfigError) as e:
                    result = Verdict.ask("gate-config", str(e))
            except Exception as e:  # noqa: BLE001
                result = Verdict.ask("gate-config", f"internal error: {e}")
            if not result and config and config["enabled"]:
                try:
                    text = stdin.read().decode("utf-8", errors="replace")
                    input = json.loads(text, parse_constant=cls._reject_constant)
                    parsed = True
                except Exception:  # noqa: BLE001
                    parsed = False
                if not parsed:
                    result = Verdict.ask("unparsable", "hook input is not valid JSON")
                else:
                    result = Gate(rules, env).gate(input, strict=config["strict"], trace=trace)
        except Exception as e:  # noqa: BLE001 - fail closed
            result = Verdict.ask("gate-config", f"internal error: {e}")
        if result:
            cls.emit(result)
        if config and config["enabled"] and config["log"]:
            cls.log_decision(config["log"], input, trace.get("rule"), result)
        # Tell the wrapper the engine ran to completion (allow = empty stdout).
        done = env.get("GATE_DONE_FILE")
        if done:
            try:
                with open(done, "w") as f:
                    f.write("done")
            except Exception:  # noqa: BLE001, S110
                pass
        return 0


def main(stdin: BinaryIO | None = None, env: Mapping[str, str] | None = None) -> int:
    return GateHook.main(stdin, env)
