"""Jev's answer -> hook output (the Lean model's `judge`)."""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..outcome import Down, HookOut
from .request import JevRequest


class JevJudge:
    """Risky answer -> ask; safe or uncertain answer -> no decision; Jev down -> ask with a warning (D11)."""

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

    @staticmethod
    def risk(probs: Mapping[str, float], prompt: Mapping[str, Any]) -> float:
        """The sum of the prompt's `ask` choices."""
        n = 0.0
        for c in prompt["ask"]:
            n += probs[c]
        return n

    @classmethod
    def top(cls, probs: Mapping[str, float], prompt: Mapping[str, Any]) -> str:
        return cls._top_of(probs, prompt["ask"])

    @classmethod
    def unavailable(cls, error: str, cfg: Mapping[str, Any]) -> HookOut:
        if error == "timeout":
            return HookOut.unavailable(Down.TIMEOUT, f"timeout after {cfg['timeoutMs']} ms")
        if error.startswith("http "):
            return HookOut.unavailable(Down.HTTP, error)
        if error == "malformed":
            return HookOut.unavailable(Down.MALFORMED, "malformed answer")
        return HookOut.unavailable(Down.NETWORK, "network error")

    @classmethod
    def judge(cls, result: Mapping[str, Any], cfg: Mapping[str, Any]) -> HookOut:
        probs = result.get("probabilities")
        if not probs:
            return cls.unavailable(str(result.get("error") or "network"), cfg)
        prompt = JevRequest._prompt_of(cfg)
        risk = cls.risk(probs, prompt)
        if risk > cfg["escalateThreshold"]:
            top = cls.top(probs, prompt)
            return HookOut("ask", f"jev: {top} p={cls._fmt(probs[top])} risk={cls._fmt(risk)}")
        return HookOut("none")
