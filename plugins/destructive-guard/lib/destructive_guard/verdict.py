"""The gate's ask decisions."""

from typing import Any


class Verdict:
    """Builds the `ask` decision dicts the gate returns."""

    @staticmethod
    def ask(rule_id: str, detail: str) -> dict[str, Any]:
        return {"decision": "ask", "reason": f"{rule_id}: {detail}"}

    @staticmethod
    def inert_flag() -> dict:
        return {"decision": "ask", "reason": "inert program with command flag"}
