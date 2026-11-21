from typing import Any

from .scope import Scope


class Cmd(list):
    """A simple command: its words, plus the heredoc / here-string payloads fed to it (`stdin`) and
    its `scope`. Compares as a plain list; hashes by identity (scope hosts are looked up by identity)."""

    stdin: list[dict[str, Any]]
    scope: Scope | None

    __hash__ = object.__hash__  # type: ignore[assignment]

    def __init__(self, words=(), stdin=None, scope=None) -> None:
        super().__init__(words)
        self.stdin = stdin if stdin is not None else []
        self.scope = scope

    @staticmethod
    def basename(token: str) -> str:
        return token.split("/")[-1]
