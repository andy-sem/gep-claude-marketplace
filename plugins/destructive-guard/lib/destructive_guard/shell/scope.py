from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cmd import Cmd


class Scope:
    """The `( … )` group or substitution a command belongs to. A `cd` inside a scope does not move
    the directory of its parent. `host` is the command that ran the shell this scope's text came from."""

    __slots__ = ("host", "parent")

    def __init__(self, parent: Scope | None) -> None:
        self.parent = parent
        self.host: Cmd | None = None
