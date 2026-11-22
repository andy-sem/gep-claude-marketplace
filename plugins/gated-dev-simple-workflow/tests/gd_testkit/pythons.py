"""Interpreter lookup (D1a) and a helper to find a Python older than the floor."""

import functools
import os
import shutil
import subprocess
from collections.abc import Mapping


class Pythons:
    _PROBE = "import sys;print(sys.version_info[:2]<(3,14))"
    _OLD_CANDIDATES = [f"python3.{minor}" for minor in range(13, 8, -1)] + ["/usr/bin/python3"]

    @staticmethod
    def find_python(env: Mapping[str, str]) -> str | None:
        """GATE_INFRA_PYTHON if set and non-empty (returned as is), else python3.14, else python3."""
        explicit = env.get("GATE_INFRA_PYTHON")
        if explicit:
            return explicit
        path = env.get("PATH")
        return shutil.which("python3.14", path=path) or shutil.which("python3", path=path)

    @staticmethod
    @functools.cache
    def _version(python: str) -> str | None:
        try:
            out = subprocess.run(
                [python, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() or None

    @classmethod
    def require_new_python(cls, env: Mapping[str, str]) -> str:
        """find_python(env), checked to be >= 3.14; RuntimeError otherwise."""
        python = cls.find_python(env)
        version = cls._version(python) if python else None
        try:
            ok = version is not None and tuple(int(p) for p in version.split(".")) >= (3, 14)
        except ValueError:
            ok = False
        if not ok:
            where = python or "PATH"
            raise RuntimeError(f"need Python >= 3.14, found {version or 'nothing'} at {where}; set GATE_INFRA_PYTHON")
        return python

    @classmethod
    def _is_old(cls, python: str) -> bool:
        try:
            out = subprocess.run([python, "-c", cls._PROBE], capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return out.stdout.strip() == "True"

    @classmethod
    def find_old_python(cls) -> str | None:
        """A Python below 3.14: OLD_PYTHON (checked; RuntimeError if not old), else the first old candidate."""
        explicit = os.environ.get("OLD_PYTHON")
        if explicit:
            if not cls._is_old(explicit):
                raise RuntimeError(f"OLD_PYTHON={explicit} is not a runnable Python below 3.14")
            return explicit
        for name in cls._OLD_CANDIDATES:
            found = shutil.which(name)
            if found and cls._is_old(found):
                return found
        return None
