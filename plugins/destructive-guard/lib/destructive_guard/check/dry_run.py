"""The gate's dry run: what would it do with a call, and what is the effective configuration."""

import os
import re
from collections.abc import Mapping
from typing import Any

from ..config import GateConfig
from ..errors import ConfigError, RulesError
from ..gate.gate import Gate


class GateDryRun:
    """Answers for one environment and working directory without running anything."""

    JEV_VARS = re.compile(r"^(GATE_JEV|TYPESAFE_API_KEY)")

    def __init__(self, env: Mapping[str, str], cwd: str | None = None) -> None:
        self.env = env
        self.cwd = cwd

    @staticmethod
    def _reject_constant(name: str) -> Any:
        raise ValueError(f"invalid JSON constant {name}")

    @staticmethod
    def _num(x: Any) -> Any:
        """JS prints 1 for 1.0."""
        return int(x) if isinstance(x, float) and x.is_integer() else x

    def _jev_summary(self) -> dict[str, Any]:
        """Jev settings for display; never includes the API key itself."""
        toggle = self.env.get("GATE_JEV")
        if not toggle or toggle.strip() in ("", "0"):
            return {"enabled": False}
        try:
            from ..jev.config import JevConfig

            cfg = JevConfig.read(self.env)
            if not cfg:
                return {"enabled": False}
            rest = {k: v for k, v in cfg.items() if k not in ("apiKey", "prompt")}
            for k in ("allowThreshold", "escalateThreshold"):
                if k in rest:
                    rest[k] = GateDryRun._num(rest[k])
            prompt = cfg["prompt"]
            return {
                "enabled": True,
                **rest,
                "apiKey": "[set]" if cfg.get("apiKey") else "[missing]",
                "prompt": (self.env.get("GATE_JEV_PROMPT") or "").strip() or "destructive",
                "question": prompt["question"],
                "ask": prompt["ask"],
                "safe": prompt["safe"],
            }
        except Exception as e:  # noqa: BLE001
            return {"enabled": True, "error": f"gate-config: {e}"}

    def effective_config(self) -> dict[str, Any]:
        """Effective configuration plus the loaded rule ids, or the config error the hook would answer with."""
        out: dict[str, Any] = {}
        try:
            config = GateConfig.read_config(self.env)
            out.update(config)
            if config["enabled"]:
                rules = GateConfig.build_rules(config)
                out["ruleIds"] = [r["id"] for r in (rules.get("rules") or []) if r.get("id")]
        except (ConfigError, RulesError) as e:
            out["error"] = f"gate-config: {e}"
        out["jev"] = self._jev_summary()
        return out

    @staticmethod
    def _answer(result: dict | None) -> dict[str, Any]:
        """{decision, reason, source}: source is the rule id or the gate's own tag (script, unparsable,
        gate-config, jev) taken from the reason prefix."""
        if not result:
            return {"decision": "none", "reason": None, "source": None}
        reason = result["reason"]
        i = reason.find(": ")
        return {"decision": result["decision"], "reason": reason, "source": reason[:i] if i > 0 else reason}

    def check_call(self, call: Mapping[str, Any], *, jev: bool = False) -> dict[str, Any]:
        """The gate's answer for one call. Never executes it."""
        bash = call["mode"] == "bash"
        if bash:
            hook_input: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": call["command"]}}
            target: dict[str, Any] = {"tool": "Bash", "command": call["command"]}
        else:
            hook_input = {"tool_name": call["tool"], "tool_input": call["input"]}
            target = {"tool": call["tool"], "input": call["input"]}
        if self.cwd:
            hook_input["cwd"] = self.cwd
        gate_env = self.env if jev else {k: v for k, v in self.env.items() if not GateDryRun.JEV_VARS.match(k)}

        try:
            config = GateConfig.read_config(self.env, cwd=self.cwd or os.getcwd())
        except ConfigError as e:
            return {**target, **GateDryRun._answer({"decision": "ask", "reason": f"gate-config: {e}"}), "rule": None}
        if not config["enabled"]:
            return {**target, "decision": "none", "reason": "gate disabled (GATE_ENABLED=0)", "source": None, "rule": None}
        try:
            rules = GateConfig.build_rules(config)
        except (ConfigError, RulesError) as e:
            return {**target, **GateDryRun._answer({"decision": "ask", "reason": f"gate-config: {e}"}), "rule": None}
        trace: dict = {}
        result = Gate(rules, gate_env, self.cwd).gate(hook_input, strict=config["strict"], trace=trace)
        jev_info = self._jev_summary()
        in_scope = (
            ("bash" if bash else "mcp") in jev_info["scope"]
            if jev_info["enabled"] and not jev_info.get("error")
            else False
        )
        return {
            **target,
            **GateDryRun._answer(result),
            "rule": GateDryRun._answer(trace["rule"]) if trace.get("rule") else None,
            "jev": "consulted" if jev else "would be consulted (pass --jev)" if in_scope else "off",
        }
