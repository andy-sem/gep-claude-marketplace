"""Reads TYPESAFE_API_KEY and the GATE_JEV_* variables into the Jev settings dict."""

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlsplit

from ..errors import JevConfigError


class JevConfig:
    """GATE_JEV_* environment variables → the Jev settings dict."""

    JEV_URL = "https://api.typesafe.ai/v1/systemone"

    DEFAULTS: ClassVar[dict[str, Any]] = {
        "escalateThreshold": 0.5,
        "model": "jev-latest",
        "timeoutMs": 1500,
    }
    MAX_TIMEOUT_MS = 30000
    LOOPBACK: ClassVar[set[str]] = {"localhost", "127.0.0.1", "::1"}

    @staticmethod
    def _optional(env: Mapping[str, str], name: str) -> str | None:
        """Empty optional variables count as unset."""
        v = env.get(name)
        if v is None or v.strip() == "":
            return None
        return v.strip()


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
            raise JevConfigError("GATE_JEV_URL is not a valid URL", "badUrl") from None
        scheme = parts.scheme.lower()
        if not scheme or (scheme in ("http", "https") and not host):
            raise JevConfigError("GATE_JEV_URL is not a valid URL", "badUrl")
        # The API key must not travel in clear text, except to a local test server.
        if scheme != "https" and not (scheme == "http" and host in cls.LOOPBACK):
            raise JevConfigError("GATE_JEV_URL must use https", "badUrl")


    @classmethod
    def read(cls, env: Mapping[str, str], *, cwd: str | Path | None = None) -> dict:
        """The Jev settings. Raises JevConfigError (with a `kind`) when the key is missing or a value is invalid.
        There is no "off" state: `GATE_ENABLED=0` removes the gate altogether."""
        from .prompt import JevPrompt

        cwd = cwd if cwd is not None else os.getcwd()
        api_key = cls._optional(env, "TYPESAFE_API_KEY")
        if not api_key:
            raise JevConfigError("TYPESAFE_API_KEY is not set", "noKey")

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

        escalate = cls._probability(env, "GATE_JEV_ESCALATE_THRESHOLD", cls.DEFAULTS["escalateThreshold"])
        try:
            prompt = JevPrompt.prompt_from_env(env, cwd=cwd)
        except JevConfigError as e:
            raise JevConfigError(str(e), "badPrompt") from None
        return {
            "apiKey": api_key,
            "url": url,
            "model": cls._optional(env, "GATE_JEV_MODEL") or cls.DEFAULTS["model"],
            "escalateThreshold": escalate,
            "timeoutMs": timeout_ms,
            "prompt": prompt,
        }
