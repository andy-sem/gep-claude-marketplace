"""Which implementation (JS or Python) a test runs against."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import DG, GD
from .pythons import require_new_python

DEFAULT_IMPL: dict[str, str] = {
    "destructive-guard": "py",
    "gated-dev-simple-workflow": "py",
}


@dataclass(frozen=True)
class Impl:
    name: Literal["js", "py"]
    plugin: str

    @property
    def interpreter_var(self) -> str:
        return "GATE_INFRA_PYTHON"

    @property
    def unavailable_reason(self) -> str:
        return "unparsable: python unavailable"

    def check_invocation(self, args: str) -> str:
        """The check command line as the docs (skill, README) write it."""
        return f'python3 "{DG}/lib/check.py" {args}'

    def _python(self) -> str:
        return require_new_python(os.environ)

    def _script(self, base: Path, py: str) -> list[str]:
        return [self._python(), "-I", str(base / py)]

    def gate_hook(self) -> list[str]:
        return ["bash", str(DG / "hooks" / "gate.sh")]

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
        """The hook command line; the hook is Python-only (P10), whatever GD_IMPL says."""
        return ["bash", str(GD / "hooks" / "run-python.sh"), str(GD / "hooks" / "notify.py")]

    def env(self) -> dict[str, str]:
        return {"GATE_INFRA_PYTHON": self._python()}


def select_impl(plugin: str, env: Mapping[str, str]) -> Impl:
    if plugin not in DEFAULT_IMPL:
        raise ValueError(f"unknown plugin {plugin!r}")
    name = env.get("GD_IMPL") or DEFAULT_IMPL[plugin]
    if name not in ("js", "py"):
        raise ValueError(f"GD_IMPL must be js or py, got {name!r}")
    if name == "js":
        raise ValueError("there is no JS implementation any more; GD_IMPL=py (the default)")
    return Impl(name, plugin)
