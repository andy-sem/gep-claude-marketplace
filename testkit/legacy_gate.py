"""The 0.8 rule gate as the old hook ran it, in-process, for the rule tests that outlive the hook.

Until L2 deletes the rule engine, its tests (corpus, packs, engine, scripts) still need a way to ask
"what did the rules say for this hook input?" now that `hook.py` only talks to Jev. Same pipeline as
the old `GateHook.main`: GateConfig.read_config -> build_rules -> Gate.gate -> `ask` JSON or nothing.
Deleted in L2 together with the code it runs.
"""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from destructive_guard.config import GateConfig
from destructive_guard.errors import ConfigError, RulesError
from destructive_guard.gate.gate import Gate
from destructive_guard.verdict import Verdict

from .envs import IsolatedEnv
from .hook_result import HookResult


class LegacyGate:
    @staticmethod
    def _reject_constant(name: str) -> Any:
        raise ValueError(f"invalid JSON constant {name}")

    @staticmethod
    def _emit(result: dict) -> str:
        return json.dumps(
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

    @classmethod
    def decide(cls, stdin: str | bytes, env: Mapping[str, str], cwd: Path | str | None = None) -> dict | None:
        """The old gate's result for one hook input: an ask dict or None."""
        where = str(cwd) if cwd is not None else os.getcwd()
        try:
            config = GateConfig.read_config(env, cwd=where)
            if not config["enabled"]:
                return None
            rules = GateConfig.build_rules(config)
        except (RulesError, ConfigError) as e:
            return Verdict.ask("gate-config", str(e))
        text = stdin.decode("utf-8", errors="replace") if isinstance(stdin, bytes) else stdin
        try:
            data = json.loads(text, parse_constant=cls._reject_constant)
        except Exception:  # noqa: BLE001
            return Verdict.ask("unparsable", "hook input is not valid JSON")
        try:
            return Gate(rules, env, where).gate(data, strict=config["strict"])
        except Exception as e:  # noqa: BLE001
            return Verdict.ask("gate-config", f"internal error: {e}")

    @classmethod
    def run(cls, stdin: str | bytes, *env: Mapping[str, str], cwd: Path | str | None = None) -> HookResult:
        """Like HookRunner.run, without a subprocess and without Jev (GATE_JEV is ignored by the rule tests)."""
        result = cls.decide(stdin, IsolatedEnv.clean(*env), cwd)
        return HookResult(0, cls._emit(result) if result else "")

    @staticmethod
    def decision(stdout: str) -> dict:
        return json.loads(stdout)["hookSpecificOutput"]
