"""Applies Jev to a call on top of the rule result: decision, audit log, the full run."""

import time
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .client import JevClient
from .request import JevRequest


class JevDecider:
    """Turns Jev's probabilities into an ask or a lift and writes the audit record."""

    @staticmethod
    def _fmt(p: float) -> str:
        """JS `toFixed(2)`: ties round up."""
        return str(Decimal(p).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _top_of(probs: Mapping[str, float], choices: list[str]) -> str:
        """Ties go to the choice listed last (the stronger one in the built-in prompts)."""
        best = choices[0]
        for c in choices[1:]:
            if probs[c] >= probs[best]:
                best = c
        return best

    @classmethod
    def jev_decision(cls, probs: Mapping[str, float], cfg: Mapping[str, Any]) -> dict | None:
        """"ask" (risk above the escalate threshold), "pass" (lift any rule ask, safe at or above the
        allow threshold) or None (no Jev decision). Jev never emits `allow`."""
        prompt = JevRequest._prompt_of(cfg)
        ask_choices, safe_choices = prompt["ask"], prompt["safe"]

        def total(choices: list[str]) -> float:
            n = 0.0
            for c in choices:
                n += probs[c]
            return n

        risk = total(ask_choices)
        if risk > cfg["escalateThreshold"]:
            top = cls._top_of(probs, ask_choices)
            return {"decision": "ask", "reason": f"jev: {top} p={cls._fmt(probs[top])} risk={cls._fmt(risk)}"}
        safe = total(safe_choices)
        if safe >= cfg["allowThreshold"]:
            top = cls._top_of(probs, list(reversed(safe_choices)))
            return {"decision": "pass", "reason": f"jev: {top} p={cls._fmt(probs[top])} safe={cls._fmt(safe)}"}
        return None

    @staticmethod
    def audit(cfg: Mapping[str, Any], record: dict) -> None:
        path = cfg.get("logPath")
        if not path:
            return
        try:
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            with open(path, "a", encoding="utf-8") as f:
                f.write(JevRequest._dumps({"ts": ts, **record}) + "\n")
        except Exception:  # noqa: BLE001, S110 - the audit log is best-effort
            pass

    @classmethod
    def run_jev(
        cls,
        call: Mapping[str, Any],
        rule_result: dict | None,
        cfg: Mapping[str, Any],
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> dict | None:
        """Applies Jev to a Bash command or an MCP call on top of the rule result and returns the final
        gate result: an ask, or None for no output."""
        rule = rule_result.get("reason") if rule_result else None
        state = JevRequest.build_state(call)
        tool = call["tool"]
        if state is None:
            cls.audit(cfg, {"tool": tool, "command": None, "rule": rule, "outcome": "skipped: .env reference", "latencyMs": 0})
            return rule_result
        if tool == "Bash":
            sent: dict = {"command": state["command"], "scripts": [s["path"] for s in state["scripts"]]}
        else:
            sent = {"input": state["input"]}
        result = JevClient(sleep=sleep).ask_jev(state, cfg, opener=opener, clock=clock)
        probabilities = result.get("probabilities")
        if not probabilities:
            cls.audit(cfg, {"tool": tool, **sent, "rule": rule, "outcome": f"fallback: {result.get('error')}", "latencyMs": result["latencyMs"]})
            return rule_result
        jev = cls.jev_decision(probabilities, cfg)
        # canLift False (GATE_JEV_CAN_LIFT=0): a safe answer leaves the rule result in place, so Jev can
        # only add asks. Missing means the default (True).
        if jev and jev["decision"] == "ask":
            final: dict | None = {"decision": "ask", "reason": jev["reason"]}
        elif jev and jev["decision"] == "pass" and cfg.get("canLift") is not False:
            final = None
        else:
            final = rule_result
        cls.audit(
            cfg,
            {
                "tool": tool,
                **sent,
                "probabilities": probabilities,
                "rule": rule,
                "jev": jev["reason"] if jev else None,
                "decision": final["decision"] if final else "pass",
                "usage": result.get("usage"),
                "latencyMs": result["latencyMs"],
            },
        )
        return final
