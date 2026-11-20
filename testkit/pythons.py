"""Interpreter lookup (D1a) and a helper to find a Python older than the floor."""

import os
import shutil
import subprocess
from collections.abc import Mapping


def find_python(env: Mapping[str, str]) -> str | None:
    """GATE_INFRA_PYTHON if set and non-empty (returned as is), else python3.14, else python3."""
    explicit = env.get("GATE_INFRA_PYTHON")
    if explicit:
        return explicit
    path = env.get("PATH")
    return shutil.which("python3.14", path=path) or shutil.which("python3", path=path)


_PROBE = "import sys;print(sys.version_info[:2]<(3,14))"
_OLD_CANDIDATES = [f"python3.{minor}" for minor in range(13, 8, -1)] + ["/usr/bin/python3"]


def _is_old(python: str) -> bool:
    try:
        out = subprocess.run([python, "-c", _PROBE], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.stdout.strip() == "True"


def find_old_python() -> str | None:
    """A Python below 3.14: OLD_PYTHON, else the first candidate that really is old."""
    explicit = os.environ.get("OLD_PYTHON")
    if explicit:
        return explicit
    for name in _OLD_CANDIDATES:
        found = shutil.which(name)
        if found and _is_old(found):
            return found
    return None
