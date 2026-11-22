"""GATE_LOG: one JSON line per handled call. Best-effort, never fails the hook."""

import json
from datetime import UTC, datetime
from typing import Any


class GateLog:
    @staticmethod
    def write(path: str | None, record: dict[str, Any]) -> None:
        """Appends `{ts, ...record}`. The record holds only redacted text (never a `.env` call's command)."""
        if not path:
            return
        try:
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            line = json.dumps({"ts": ts, **record}, ensure_ascii=False, separators=(",", ":"))
            with open(path, "a", encoding="utf-8", errors="replace") as f:
                f.write(line + "\n")
        except Exception:  # noqa: BLE001, S110 - the log is best-effort
            pass
