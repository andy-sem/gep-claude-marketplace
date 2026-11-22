"""What the hook prints: a decision (`none` or `ask`, never allow or deny) and an optional warning.

The Lean model's `HookOut` (formal/SimpleGate.lean). `HookOut.to_json` is the only place
that writes hook output for `PreToolUse`.
"""

import json
from dataclasses import dataclass
from typing import Literal

from .down import Down


@dataclass(frozen=True)
class HookOut:
    decision: Literal["none", "ask"]  # no "allow"/"deny" in the type
    reason: str | None = None  # set iff decision == "ask"
    warning: Down | None = None
    detail: str | None = None  # e.g. "http 503", "timeout after 1500 ms"

    OFF_SWITCH = "GATE_ENABLED=0 turns the gate off."

    def __post_init__(self) -> None:
        if (self.decision == "ask") != (self.reason is not None):
            raise ValueError("a reason comes with ask, and only with ask")
        if self.warning is not None and self.decision == "ask" and not self.warning.asks:
            raise ValueError(f"warning {self.warning} must not come with ask")
        if self.warning is not None and self.decision == "none" and self.warning.asks:
            raise ValueError(f"warning {self.warning} must come with ask")

    @classmethod
    def fault(cls, kind: Down, detail: str | None = None) -> HookOut:
        """A plugin fault (D12): ask with reason `plugin-fault: <text>` and a warning."""
        if not kind.plugin_fault:
            raise ValueError(f"{kind} is not a plugin fault")
        text = {
            Down.BAD_INPUT: "bad hook input",
            Down.PYTHON_MISSING: "no Python >= 3.14 found (set GATE_INFRA_PYTHON)",
            Down.INTERNAL_ERROR: f"internal error: {detail or 'unknown'}",
        }[kind]
        return cls("ask", f"plugin-fault: {text}", kind, detail)

    @classmethod
    def unavailable(cls, kind: Down, detail: str) -> HookOut:
        """Jev is configured but did not answer (D11): ask with reason `jev-unavailable: <detail>`."""
        if not kind.jev_unavailable:
            raise ValueError(f"{kind} is not a Jev failure")
        return cls("ask", f"jev-unavailable: {detail}", kind, detail)

    def message(self) -> str | None:
        """The `systemMessage` text, or None without a warning."""
        w = self.warning
        if w is None:
            return None
        d = self.detail or ""
        text = {
            Down.TIMEOUT: f"Jev did not answer in time ({d.removeprefix('timeout after ')}); asking you instead.",
            Down.HTTP: f"Jev returned {d}; asking you instead.",
            Down.NETWORK: "Jev could not be reached; asking you instead.",
            Down.MALFORMED: "Jev's answer was malformed; asking you instead.",
            Down.ENV_REFERENCE: "call mentions a .env file and was not sent to Jev; Claude Code's permissions apply",
            Down.BAD_INPUT: "could not read the hook input; asking you instead.",
            Down.PYTHON_MISSING: "no Python >= 3.14 found (set GATE_INFRA_PYTHON); asking you instead.",
            Down.INTERNAL_ERROR: f"internal error ({d or 'unknown'}); asking you instead.",
        }[w]
        return f"destructive-guard: {text if w is Down.ENV_REFERENCE else f'{text} {self.OFF_SWITCH}'}"

    def to_json(self) -> str | None:
        """ask -> permissionDecision; a warning -> systemMessage; neither -> None (no output)."""
        out: dict = {}
        if self.decision == "ask":
            out["hookSpecificOutput"] = {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": self.reason,
            }
        message = self.message()
        if message is not None:
            out["systemMessage"] = message
        if not out:
            return None
        return json.dumps(out, ensure_ascii=False, separators=(",", ":"))
