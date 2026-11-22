"""Exceptions raised by destructive-guard."""


class UnparsableError(Exception):
    pass


class RulesError(Exception):
    pass


class ConfigError(Exception):
    pass


class JevConfigError(Exception):
    """A Jev setting is missing or invalid. `kind` feeds the session warning: noKey, badUrl, badPrompt, badValue."""

    def __init__(self, message: str, kind: str = "badValue") -> None:
        super().__init__(message)
        self.kind = kind


class UsageError(Exception):
    pass
