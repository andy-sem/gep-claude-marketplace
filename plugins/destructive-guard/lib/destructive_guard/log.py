"""GATE_LOG: one JSON line per handled call. Best-effort, never fails the hook."""

import json
import os
from datetime import UTC, datetime
from typing import Any


class GateLog:
    @staticmethod
    def open_for_append(path: str):
        """Opens `path` for appending, creating missing parent directories. Raises OSError."""
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return open(path, "a", encoding="utf-8", errors="replace")

    @staticmethod
    def problem(path: str | None) -> str | None:
        """Why `path` cannot be appended to, or None. Creates the file (and its directories) like a write would."""
        if not path:
            return None
        try:
            with GateLog.open_for_append(path):
                pass
        except OSError as e:
            return e.strerror or type(e).__name__
        return None

    @staticmethod
    def write(path: str | None, record: dict[str, Any]) -> None:
        """Appends `{ts, ...record}`. The record holds only redacted text (never a `.env` call's command)."""
        if not path:
            return
        try:
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            line = json.dumps({"ts": ts, **record}, ensure_ascii=False, separators=(",", ":"))
            with GateLog.open_for_append(path) as f:
                f.write(line + "\n")
        except Exception:  # noqa: BLE001, S110 - the log is best-effort; SessionCheck reports an unwritable path
            pass
