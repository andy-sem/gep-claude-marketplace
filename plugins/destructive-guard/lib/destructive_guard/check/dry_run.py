"""The gate's dry run: what would the hook do with a call, and what is the effective configuration.

Interim shape until L4 rewrites `check` for the Jev hook: a call check asks the hook's own decision
function (so it contacts Jev and costs one request); there is no rule engine to consult.
"""

import os
from collections.abc import Mapping
from typing import Any

from ..config import GateConfig
from ..errors import ConfigError, JevConfigError
from ..hook import GateHook
from ..jev.config import JevConfig
from ..session import SessionCheck


class GateDryRun:
    """Answers for one environment without running anything."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = env

    @staticmethod
    def _reject_constant(name: str) -> Any:
        raise ValueError(f"invalid JSON constant {name}")

    @staticmethod
    def _num(x: Any) -> Any:
        """JS prints 1 for 1.0."""
        return int(x) if isinstance(x, float) and x.is_integer() else x

    def _jev_summary(self) -> dict[str, Any]:
        """Jev settings for display; never includes the API key itself."""
        try:
            cfg = JevConfig.read(self.env)
        except JevConfigError as e:
            return {"apiKey": "[missing]" if e.kind == "noKey" else "[set]", "error": str(e)}
        prompt = cfg["prompt"]
        return {
            "url": cfg["url"],
            "model": cfg["model"],
            "escalateThreshold": GateDryRun._num(cfg["escalateThreshold"]),
            "timeoutMs": cfg["timeoutMs"],
            "apiKey": "[set]",
            "prompt": (self.env.get("GATE_JEV_PROMPT") or "").strip() or "destructive",
            "question": prompt["question"],
            "ask": prompt["ask"],
        }

    def effective_config(self) -> dict[str, Any]:
        """The gate settings, the Jev settings (key redacted) and the session warning, if any."""
        out: dict[str, Any] = {}
        try:
            out.update(GateConfig.read(self.env))
        except ConfigError as e:
            out["error"] = str(e)
        out["jev"] = self._jev_summary()
        out["sessionWarning"] = SessionCheck.message(self.env)
        return out

    def check_call(self, call: Mapping[str, Any]) -> dict[str, Any]:
        """The hook's answer for one call: {tool, command|input, decision, reason, warning, risk}."""
        if call["mode"] == "bash":
            hook_call: dict[str, Any] = {"tool": "Bash", "command": call["command"]}
            target: dict[str, Any] = {"tool": "Bash", "command": call["command"]}
        else:
            hook_call = {"tool": call["tool"], "input": call["input"]}
            target = {"tool": call["tool"], "input": call["input"]}
        try:
            gate = GateConfig.read(self.env, cwd=os.getcwd())
        except ConfigError as e:
            return {**target, "decision": "none", "reason": None, "warning": f"misconfigured: {e}", "risk": None}
        if not gate["enabled"]:
            return {**target, "decision": "none", "reason": "gate disabled (GATE_ENABLED=0)", "warning": None, "risk": None}
        try:
            cfg = JevConfig.read(self.env)
        except JevConfigError as e:
            return {**target, "decision": "none", "reason": None, "warning": f"misconfigured: {e}", "risk": None}
        record: dict[str, Any] = {}
        out = GateHook.decide(hook_call, cfg, record)
        return {
            **target,
            "decision": out.decision,
            "reason": out.reason,
            "warning": out.message(),
            "risk": record.get("risk"),
        }
