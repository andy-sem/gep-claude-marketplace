"""The command lines tests use to run each plugin entry point."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

from . import DG, GD
from .pythons import Pythons


@dataclass(frozen=True)
class Impl:
    DEFAULT: ClassVar[dict[str, str]] = {
        "destructive-guard": "py",
        "gated-dev-simple-workflow": "py",
    }

    name: Literal["py"]
    plugin: str

    @property
    def interpreter_var(self) -> str:
        return "GATE_INFRA_PYTHON"

    def check_invocation(self, args: str) -> str:
        """The check command line as the docs (skill, README) write it."""
        return f'python3 "{DG}/lib/check.py" {args}'

    def _python(self) -> str:
        return Pythons.require_new_python(os.environ)

    def _script(self, base: Path, py: str) -> list[str]:
        return [self._python(), "-I", str(base / py)]

    def gate_hook(self) -> list[str]:
        return ["bash", str(DG / "hooks" / "gate.sh")]

    def session_hook(self) -> list[str]:
        return ["bash", str(DG / "hooks" / "session-start.sh")]

    def env_guard(self) -> list[str]:
        return ["bash", str(DG / "hooks" / "env-guard.sh")]

    def check(self) -> list[str]:
        return [self._python(), "-I", str(DG / "lib" / "check.py")]

    def launch(self) -> list[str]:
        return self._script(GD / "scripts", "launch.py")

    def watch_pr(self, fast: bool = False) -> list[str]:
        """The watcher command line; `fast` makes every poll interval elapse at once (see _fast_sleep.py)."""
        if not fast:
            return self._script(GD / "scripts", "watch_pr.py")
        return [self._python(), "-I", str(Path(__file__).resolve().parent / "_fast_sleep.py"), str(GD / "scripts" / "watch_pr.py")]

    def notify(self) -> list[str]:
        """The hook command line; the hook runs through run-python.sh."""
        return ["bash", str(GD / "hooks" / "run-python.sh"), str(GD / "hooks" / "notify.py")]

    def env(self) -> dict[str, str]:
        return {"GATE_INFRA_PYTHON": self._python()}


    @classmethod
    def select(cls, plugin: str, env: Mapping[str, str]) -> Impl:
        if plugin not in cls.DEFAULT:
            raise ValueError(f"unknown plugin {plugin!r}")
        return cls("py", plugin)
