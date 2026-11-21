"""Effective destructive-guard configuration from environment variables (port of config.mjs).

All env parsing for the rules layer lives here; the Jev variables are read by gate_jev.
`read_config` is pure (env in, config out) and raises ConfigError for any value it does not
understand, so the gate can fail closed instead of guessing.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import ConfigError, RulesError
from .paths import project_dir, project_path
from .rules.rule_loader import RuleLoader, Rules
from .rules.rule_parser import RuleParser

__all__ = [
    "DEFAULT_CHECKS",
    "ConfigError",
    "RulesError",
    "available_packs",
    "build_rules",
    "project_dir",
    "project_path",
    "read_config",
]


DEFAULT_CHECKS = [p for p in RuleLoader.DEFAULT_PACKS if p != "base"]

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _value(env: Mapping[str, str], name: str) -> str | None:
    """Unset or empty means "use the default"."""
    v = env.get(name)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _flag(env: Mapping[str, str], name: str, fallback: bool) -> bool:
    v = _value(env, name)
    if v is None:
        return fallback
    lower = v.lower()
    if lower in _TRUE:
        return True
    if lower in _FALSE:
        return False
    raise ConfigError(f'{name} must be 0 or 1, got "{v}"')


def _list(v: str, sep: str) -> list[str]:
    return [s for s in (part.strip() for part in v.split(sep)) if s]


def available_packs(directory: str | Path = RuleLoader.PACKS_DIR) -> list[str]:
    """Pack names shipped in packs/ (without .json)."""
    return sorted(f.name[: -len(".json")] for f in Path(directory).iterdir() if f.name.endswith(".json"))


def _read_checks(env: Mapping[str, str], packs: list[str]) -> list[str]:
    v = _value(env, "GATE_CHECKS")
    if v is None:
        return list(DEFAULT_CHECKS)
    names = _list(v, ",")
    if names == ["none"]:
        return []
    if "none" in names:
        raise ConfigError("GATE_CHECKS: none cannot be combined with packs")
    for n in names:
        if n not in packs:
            raise ConfigError(f'GATE_CHECKS: unknown pack "{n}" (available: {", ".join(packs)})')
    return list(dict.fromkeys(names))


def read_config(
    env: Mapping[str, str],
    *,
    packs: list[str] | None = None,
    cwd: str | Path | None = None,
) -> dict[str, Any]:
    """env -> {enabled, packs, rulesFiles, disableRules, envGuard, strict, log}.

    `packs` are full pack names in load order (`base` first) or [] for none. Relative paths
    (rules files, log) resolve against the project (paths.py); `cwd` only matters when
    CLAUDE_PROJECT_DIR is unset.
    """
    if packs is None:
        packs = available_packs()
    if cwd is None:
        cwd = os.getcwd()

    def path(p: str) -> str:
        return project_path(p, env, cwd)

    enabled = _flag(env, "GATE_ENABLED", True)
    env_guard = _flag(env, "GATE_ENV_GUARD", True)
    strict = _flag(env, "GATE_STRICT", False)
    log_value = _value(env, "GATE_LOG")
    log = None if log_value is None else path(log_value)

    # GATE_RULES (deprecated): one rules file replacing every pack.
    legacy = _value(env, "GATE_RULES")
    if legacy is not None:
        if _value(env, "GATE_CHECKS") is not None or _value(env, "GATE_RULES_FILE") is not None:
            raise ConfigError(
                "GATE_RULES cannot be combined with GATE_CHECKS or GATE_RULES_FILE "
                "(use GATE_CHECKS=none GATE_RULES_FILE=…)"
            )
        checks: list[str] = []
        rules_files = [path(legacy)]
    else:
        checks = _read_checks(env, packs)
        files = _value(env, "GATE_RULES_FILE")
        rules_files = [] if files is None else [path(f) for f in _list(files, ":")]
    pack_names = ["base", *(c for c in checks if c != "base")] if checks else []
    if not pack_names and not rules_files:
        raise ConfigError("GATE_CHECKS=none needs GATE_RULES_FILE")

    disabled = _value(env, "GATE_DISABLE_RULES")
    disable_rules = [] if disabled is None else list(dict.fromkeys(_list(disabled, ",")))

    return {
        "enabled": enabled,
        "packs": pack_names,
        "rulesFiles": rules_files,
        "disableRules": disable_rules,
        "envGuard": env_guard,
        "strict": strict,
        "log": log,
    }


def build_rules(config: Mapping[str, Any]) -> Rules:
    """Load the packs and extra files of `config`, drop disabled rules and return parsed rules.
    Raises RulesError (bad files) or ConfigError (unknown rule id)."""
    raw = RuleLoader.compose_rules([*(RuleLoader.pack_path(p) for p in config["packs"]), *config["rulesFiles"]])
    if config["disableRules"]:
        rules = raw["rules"] if isinstance(raw.get("rules"), list) else []
        ids = {r.get("id") if isinstance(r, dict) else None for r in rules}
        unknown = [i for i in config["disableRules"] if i not in ids]
        if unknown:
            raise ConfigError(f"GATE_DISABLE_RULES: unknown rule id {', '.join(f'"{u}"' for u in unknown)}")
        drop = set(config["disableRules"])
        raw["rules"] = [r for r in rules if not (isinstance(r, dict) and r.get("id") in drop)]
    return RuleParser.parse_rules(raw)
