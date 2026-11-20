"""Which implementation (JS or Python) a test runs against."""

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from . import DG, GD
from .pythons import find_python

DEFAULT_IMPL: dict[str, str] = {
    "destructive-guard": "js",
    "gated-dev-simple-workflow": "js",
}


@dataclass(frozen=True)
class Impl:
    name: Literal["js", "py"]
    plugin: str

    def _python(self) -> str:
        python = find_python(os.environ)
        if python is None:
            raise RuntimeError("no Python found (set GATE_INFRA_PYTHON or install python3.14)")
        return python

    def _script(self, base, js: str, py: str) -> list[str]:
        if self.name == "js":
            return ["node", str(base / js)]
        return [self._python(), "-I", str(base / py)]

    def gate_hook(self) -> list[str]:
        return ["bash", str(DG / "hooks" / "gate.sh")]

    def env_guard(self) -> list[str]:
        return ["bash", str(DG / "hooks" / "env-guard.sh")]

    def check(self) -> list[str]:
        return self._script(DG / "lib", "check.mjs", "check.py")

    def launch(self) -> list[str]:
        return self._script(GD / "scripts", "launch.mjs", "launch.py")

    def watch_pr(self) -> list[str]:
        return self._script(GD / "scripts", "watch-pr.mjs", "watch_pr.py")

    def notify(self) -> list[str]:
        if self.name == "js":
            return ["bash", str(GD / "hooks" / "notify.sh")]
        return ["bash", str(GD / "hooks" / "run-python.sh"), str(GD / "hooks" / "notify.py")]

    def env(self) -> dict[str, str]:
        if self.name == "js":
            return {"GATE_INFRA_NODE": shutil.which("node") or ""}
        return {"GATE_INFRA_PYTHON": self._python()}


def select_impl(plugin: str, env: Mapping[str, str]) -> Impl:
    if plugin not in DEFAULT_IMPL:
        raise ValueError(f"unknown plugin {plugin!r}")
    name = env.get("GD_IMPL") or DEFAULT_IMPL[plugin]
    if name not in ("js", "py"):
        raise ValueError(f"GD_IMPL must be js or py, got {name!r}")
    return Impl(name, plugin)
