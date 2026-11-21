"""Shared logic of the entry-stub tests (one test file per plugin uses it)."""

import ast
import os
import re
import subprocess
from pathlib import Path
from typing import ClassVar

from . import DG, GD
from .pythons import Pythons


class EntryStubs:
    # (stub path, package module the stub imports)
    STUBS: ClassVar[list[tuple[Path, str]]] = [
        (DG / "lib" / "gate_main.py", "gate_main"),
        (DG / "lib" / "check.py", "check"),
        (GD / "scripts" / "launch.py", "launch"),
        (GD / "scripts" / "watch_pr.py", "watch_pr"),
        (GD / "hooks" / "notify.py", "notify"),
    ]
    TOO_OLD = re.compile(r"^needs Python >= 3\.14 \(found 3\.\d+ at .+\); set GATE_INFRA_PYTHON\n$")

    @classmethod
    def stubs_of(cls, plugin_dir: Path) -> list[tuple[Path, str]]:
        return [(p, m) for p, m in cls.STUBS if plugin_dir in p.parents]

    @staticmethod
    def stub_id(param: tuple[Path, str]) -> str:
        return param[0].name

    @staticmethod
    def check_parses_as_37(stub: Path) -> None:
        ast.parse(stub.read_text(), filename=str(stub), feature_version=(3, 7))

    @classmethod
    def check_old_python_exit_3(cls, old_python: str, stub: Path) -> None:
        proc = subprocess.run([old_python, "-I", str(stub)], capture_output=True, text=True, check=False)
        assert proc.returncode == 3, proc.stderr
        assert cls.TOO_OLD.match(proc.stderr), proc.stderr
        assert proc.stdout == ""

    @staticmethod
    def check_314_imports_package(tmp_path: Path, stub: Path, module: str) -> None:
        for planted in ("destructive_guard.py", "gated_dev.py"):
            (tmp_path / planted).write_text("raise SystemExit(99)\n")
        python = Pythons.require_new_python(os.environ)
        proc = subprocess.run([python, "-I", str(stub)], capture_output=True, text=True, cwd=tmp_path, check=False)
        assert proc.returncode == 2, proc.stderr
        assert proc.stderr == f"{module}: not implemented yet\n"
