"""Redaction of commands, scripts and MCP inputs before they are sent to Jev."""

import re
from typing import Any, ClassVar


class Redactor:
    """Replaces secrets in what Jev is sent and drops .env references."""

    R = "[REDACTED]"
    ENV_LINE_REMOVED = "[line removed: .env reference]"
    # JS `\s`: ASCII whitespace plus the Unicode spaces (Python's `\s` with re.ASCII is ASCII only).
    _WS = "\t\n\v\f\r    -     　﻿"
    _SECRET_NAME = r"[\w-]*(?:token|passw(?:or)?d|pwd|secret|api[_-]?key|apikey|auth\w*|credential|private[_-]?key)[\w-]*"
    _FLAGS = re.ASCII | re.IGNORECASE
    _SECRET_KEY_RE = re.compile(f"{_SECRET_NAME}", _FLAGS)
    _SQL_KEYS: ClassVar[set[str]] = {"query", "sql", "statement"}

    _URL_CREDENTIALS = re.compile(rf"\b([a-z][a-z0-9+.-]*://)[^{_WS}/@'\"]+@", _FLAGS)
    _AUTH_SCHEME = re.compile(rf"\b(Bearer|Basic|Token)[{_WS}]+[^{_WS}'\"]+", _FLAGS)
    # The lookbehind starts a match only at the beginning of a name run. The same matches as JS (a name
    # is the whole [\w-] run around the keyword), but a long keyword-free run is scanned once, not once
    # per start position (quadratic backtracking).
    _SECRET_ASSIGN = re.compile(
        rf"(?<![\w-])({_SECRET_NAME})([{_WS}]*[=:][{_WS}]*)(\"[^\"]*\"|'[^']*'|[^{_WS}'\"]+)",
        _FLAGS,
    )
    _SECRET_FLAG = re.compile(
        rf"([{_WS}]--?{_SECRET_NAME})([{_WS}]+)(\"[^\"]*\"|'[^']*'|[^{_WS}'\"-][^{_WS}'\"]*)",
        _FLAGS,
    )
    _ENV_ASSIGN = re.compile(
        rf"(^|[{_WS};&|(])([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|[^{_WS};&|)]*)",
        re.ASCII,
    )
    _HEX_RUN = re.compile(r"\b[0-9a-f]{32,}\b", _FLAGS)
    _LONG_RUN = re.compile(r"[A-Za-z0-9+/_-]{32,}={0,2}", re.ASCII)
    _ENV_FILE = re.compile(r"(^|[^A-Za-z0-9])\.env", re.ASCII)
    _DOLLAR_QUOTED = re.compile(r"(\$[A-Za-z_]\w*\$|\$\$)[\s\S]*?\1", re.ASCII)
    _SQL_STRING = re.compile(r"'(?:[^']|'')*'")

    @classmethod
    def references_env_file(cls, command: str) -> bool:
        """Commands that mention .env files (`.env`, `apps/x/.env.local`, `.envrc`) are never sent."""
        return cls._ENV_FILE.search(command) is not None

    @staticmethod
    def _looks_encoded(run: str) -> bool:
        return bool(
            re.search("[0-9]", run)
            and re.search("[A-Z]", run)
            and re.search("[a-z]", run)
        )

    @classmethod
    def _redact_text(cls, text: str, *, env_assignments: bool = True) -> str:
        """The redaction rules shared by commands, scripts and MCP inputs. `env_assignments` is off for
        SQL, where `id=5` is not a shell assignment."""
        # https://user:pass@host -> https://[REDACTED]@host
        out = cls._URL_CREDENTIALS.sub(lambda m: f"{m[1]}{cls.R}@", text)
        out = cls._AUTH_SCHEME.sub(lambda m: f"{m[1]} {cls.R}", out)
        # NAME=value / NAME: value where NAME looks like a secret
        out = cls._SECRET_ASSIGN.sub(lambda m: f"{m[1]}{m[2]}{cls.R}", out)
        # --password value / -token value
        out = cls._SECRET_FLAG.sub(lambda m: f"{m[1]}{m[2]}{cls.R}", out)
        if env_assignments:
            # Environment assignments: FOO=bar cmd, export FOO=bar, env FOO=bar cmd
            out = cls._ENV_ASSIGN.sub(lambda m: f"{m[1]}{m[2]}={cls.R}", out)
        out = cls._HEX_RUN.sub(cls.R, out)
        return cls._LONG_RUN.sub(
            lambda m: cls.R if cls._looks_encoded(m[0]) else m[0], out
        )

    @classmethod
    def redact(cls, command: str) -> str | None:
        """The command with secrets replaced, or None when it must not be sent."""
        if cls.references_env_file(command):
            return None
        return cls._redact_text(command)

    @classmethod
    def _drop_env_lines(cls, text: str) -> str:
        """Lines that reference an .env file are removed instead of skipping the call."""
        return "\n".join(
            cls.ENV_LINE_REMOVED if cls.references_env_file(line) else line
            for line in text.split("\n")
        )

    @classmethod
    def _redact_sql_literals(cls, sql: str) -> str:
        """Single-quoted literals (with '' escapes) and dollar-quoted bodies hold data, not structure:
        Jev needs the statement kind, not the values."""
        out = cls._DOLLAR_QUOTED.sub(lambda m: f"{m[1]}{cls.R}{m[1]}", sql)
        return cls._SQL_STRING.sub(f"'{cls.R}'", out)

    @classmethod
    def _redact_mcp_value(cls, value: Any, key: str) -> Any:
        if isinstance(value, str):
            text = cls._drop_env_lines(value)
            if key in cls._SQL_KEYS:
                return cls._redact_text(
                    cls._redact_sql_literals(text), env_assignments=False
                )
            return cls._redact_text(text)
        if isinstance(value, list):
            return [cls._redact_mcp_value(v, key) for v in value]
        if isinstance(value, dict):
            return {
                k: cls.R
                if cls._SECRET_KEY_RE.fullmatch(k)
                else cls._redact_mcp_value(v, k)
                for k, v in value.items()
            }
        return value

    @classmethod
    def redact_mcp_input(cls, tool_input: Any) -> str:
        """An MCP tool input as redacted JSON text."""
        redacted = cls._redact_mcp_value({} if tool_input is None else tool_input, "")
        from .request import JevRequest

        return JevRequest._dumps(redacted)
