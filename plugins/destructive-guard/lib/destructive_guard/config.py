"""The gate's own settings from environment variables: GATE_ENABLED, GATE_ENV_GUARD and GATE_LOG.

The Jev variables are read by the jev package. `read` is pure (env in, config out) and raises
ConfigError for a value it does not understand.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from .errors import ConfigError
from .paths import ProjectDir


class GateConfig:
    _TRUE: ClassVar[set[str]] = {"1", "true", "yes", "on"}
    _FALSE: ClassVar[set[str]] = {"0", "false", "no", "off"}

    @staticmethod
    def _value(env: Mapping[str, str], name: str) -> str | None:
        """Unset or empty means "use the default"."""
        v = env.get(name)
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @classmethod
    def _flag(cls, env: Mapping[str, str], name: str, fallback: bool) -> bool:
        v = cls._value(env, name)
        if v is None:
            return fallback
        lower = v.lower()
        if lower in cls._TRUE:
            return True
        if lower in cls._FALSE:
            return False
        raise ConfigError(f'{name} must be 0 or 1, got "{v}"')

    @classmethod
    def read(cls, env: Mapping[str, str], *, cwd: str | Path | None = None) -> dict[str, Any]:
        """env -> {enabled, envGuard, log}. Raises ConfigError for a value it does not understand."""
        enabled = cls._flag(env, "GATE_ENABLED", True)
        env_guard = cls._flag(env, "GATE_ENV_GUARD", True)
        log_value = cls._value(env, "GATE_LOG")
        log = None if log_value is None else ProjectDir.project_path(log_value, env, cwd if cwd is not None else os.getcwd())
        return {"enabled": enabled, "envGuard": env_guard, "log": log}
