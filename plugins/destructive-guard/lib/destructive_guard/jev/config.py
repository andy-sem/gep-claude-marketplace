"""Reads the GATE_JEV_* variables into the Jev settings dict (None when Jev is off)."""

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlsplit

from ..errors import JevConfigError
from ..paths import project_path


class JevConfig:
    """GATE_JEV_* environment variables → the Jev settings dict."""

    JEV_URL = "https://api.typesafe.ai/v1/systemone"

    DEFAULTS: ClassVar[dict[str, Any]] = {
        "allowThreshold": 0.95,
        "escalateThreshold": 0.5,
        "model": "jev-latest",
        "timeoutMs": 1500,
    }
    MAX_TIMEOUT_MS = 30000
    LOOPBACK: ClassVar[set[str]] = {"localhost", "127.0.0.1", "::1"}
    SCOPES: ClassVar[list[str]] = ["bash", "mcp"]

    @staticmethod
    def _optional(env: Mapping[str, str], name: str) -> str | None:
        """Empty optional variables count as unset."""
        v = env.get(name)
        if v is None or v.strip() == "":
            return None
        return v.strip()


    @classmethod
    def _scope(cls, env: Mapping[str, str]) -> list[str]:
        """GATE_JEV_SCOPE: comma list of call kinds sent to Jev (default: all)."""
        raw = cls._optional(env, "GATE_JEV_SCOPE")
        if raw is None:
            return list(cls.SCOPES)
        items = [s.strip().lower() for s in raw.split(",")]
        if any(s not in cls.SCOPES for s in items):
            raise JevConfigError(f"GATE_JEV_SCOPE must be a comma list of {', '.join(cls.SCOPES)}")
        return [s for s in cls.SCOPES if s in items]


    @classmethod
    def _can_lift(cls, env: Mapping[str, str]) -> bool:
        """GATE_JEV_CAN_LIFT: 1 (default) lets a confident safe answer lift a rule ask; 0 only adds asks."""
        raw = cls._optional(env, "GATE_JEV_CAN_LIFT")
        if raw is None or raw == "1":
            return True
        if raw == "0":
            return False
        raise JevConfigError("GATE_JEV_CAN_LIFT must be 0 or 1")


    _PROBABILITY = re.compile(r"0(\.[0-9]+)?|1(\.0+)?|\.[0-9]+")


    @classmethod
    def _probability(cls, env: Mapping[str, str], name: str, fallback: float) -> float:
        raw = cls._optional(env, name)
        if raw is None:
            return fallback
        if not cls._PROBABILITY.fullmatch(raw):
            raise JevConfigError(f"{name} must be a number from 0 to 1")
        n = float(raw)
        if not 0 <= n <= 1:
            raise JevConfigError(f"{name} must be a number from 0 to 1")
        return n


    @classmethod
    def _check_url(cls, url: str) -> None:
        try:
            parts = urlsplit(url)
            parts.port  # noqa: B018 - raises ValueError for a bad port
            host = parts.hostname
        except ValueError:
            raise JevConfigError("GATE_JEV_URL is not a valid URL") from None
        scheme = parts.scheme.lower()
        if not scheme or (scheme in ("http", "https") and not host):
            raise JevConfigError("GATE_JEV_URL is not a valid URL")
        # The API key must not travel in clear text, except to a local test server.
        if scheme != "https" and not (scheme == "http" and host in cls.LOOPBACK):
            raise JevConfigError("GATE_JEV_URL must use https")


    @classmethod
    def read(cls, env: Mapping[str, str], *, cwd: str | Path | None = None) -> dict | None:
        """None when Jev is off. Raises JevConfigError when Jev is on and a variable is missing or invalid."""
        from .prompt import JevPrompt

        cwd = cwd if cwd is not None else os.getcwd()
        toggle = cls._optional(env, "GATE_JEV")
        if toggle is None or toggle == "0":
            return None
        if toggle != "1":
            raise JevConfigError("GATE_JEV must be 1 or unset")

        api_key = cls._optional(env, "TYPESAFE_API_KEY")
        if not api_key:
            raise JevConfigError("GATE_JEV=1 but TYPESAFE_API_KEY is not set")

        raw_timeout = cls._optional(env, "GATE_JEV_TIMEOUT_MS")
        timeout_ms = cls.DEFAULTS["timeoutMs"]
        if raw_timeout is not None:
            if not re.fullmatch(r"[0-9]+", raw_timeout):
                raise JevConfigError(f"GATE_JEV_TIMEOUT_MS must be an integer from 1 to {cls.MAX_TIMEOUT_MS}")
            timeout_ms = int(raw_timeout)
        if timeout_ms < 1 or timeout_ms > cls.MAX_TIMEOUT_MS:
            raise JevConfigError(f"GATE_JEV_TIMEOUT_MS must be an integer from 1 to {cls.MAX_TIMEOUT_MS}")

        url = cls._optional(env, "GATE_JEV_URL") or cls.JEV_URL
        cls._check_url(url)

        log = cls._optional(env, "GATE_JEV_LOG")
        return {
            "apiKey": api_key,
            "url": url,
            "model": cls._optional(env, "GATE_JEV_MODEL") or cls.DEFAULTS["model"],
            "allowThreshold": cls._probability(env, "GATE_JEV_ALLOW_THRESHOLD", cls.DEFAULTS["allowThreshold"]),
            "escalateThreshold": cls._probability(env, "GATE_JEV_ESCALATE_THRESHOLD", cls.DEFAULTS["escalateThreshold"]),
            "timeoutMs": timeout_ms,
            "logPath": None if log is None else project_path(log, env, cwd),
            "scope": cls._scope(env),
            "canLift": cls._can_lift(env),
            "prompt": JevPrompt.prompt_from_env(env, cwd=cwd),
        }
