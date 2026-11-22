"""The command lines tests use to run each plugin entry point."""

import os
from pathlib import Path

from . import GD
from .pythons import Pythons


class Entrypoints:
    """Shipped hooks and scripts as argv lists, run on a Python >= 3.14 (`GATE_INFRA_PYTHON` first)."""

    @staticmethod
    def _python() -> str:
        return Pythons.require_new_python(os.environ)

    @classmethod
    def _script(cls, path: Path) -> list[str]:
        return [cls._python(), "-I", str(path)]

    @classmethod
    def launch(cls) -> list[str]:
        return cls._script(GD / "scripts" / "launch.py")

    @classmethod
    def watch_pr(cls, fast: bool = False) -> list[str]:
        """The watcher command line; `fast` makes every poll interval elapse at once (see _fast_sleep.py)."""
        script = GD / "scripts" / "watch_pr.py"
        if not fast:
            return cls._script(script)
        return [*cls._script(Path(__file__).resolve().parent / "_fast_sleep.py"), str(script)]

    @staticmethod
    def notify() -> list[str]:
        """The hook command line; the hook runs through run-python.sh."""
        return ["bash", str(GD / "hooks" / "run-python.sh"), str(GD / "hooks" / "notify.py")]

    @classmethod
    def env(cls) -> dict[str, str]:
        return {"GATE_INFRA_PYTHON": cls._python()}
