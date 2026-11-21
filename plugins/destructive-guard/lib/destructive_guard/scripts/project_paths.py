"""Project root and path helpers for the script scan."""

import os
import re
from collections.abc import Mapping

from ..rules.rule_loader import Rules


class ProjectPaths:
    """Project root, path joining and glob matching used by the script scan."""

    @staticmethod
    def _basename(path: str) -> str:
        return os.path.basename(path.rstrip("/")) if path.strip("/") else ""

    @staticmethod
    def _join(base: str, rel: str) -> str:
        return os.path.normpath(f"{base}/{rel}")

    @staticmethod
    def _resolve(base: str, rel: str) -> str:
        return os.path.abspath(os.path.join(base, rel))

    @staticmethod
    def _at(items: list[str], index: int) -> str | None:
        return items[index] if 0 <= index < len(items) else None

    @staticmethod
    def real_or_self(path: str) -> str:
        try:
            return os.path.realpath(path, strict=True)
        except (OSError, ValueError):
            return path

    @classmethod
    def find_project_root(cls, cwd: str, env: Mapping[str, str] | None = None) -> str:
        """The nearest ancestor of `cwd` that has a `.git` entry (a directory, or the file a worktree
        has), else CLAUDE_PROJECT_DIR, else `cwd`. Always realpath'd."""
        if env is None:
            env = os.environ
        directory = os.path.abspath(cwd)
        while True:
            if os.path.exists(os.path.join(directory, ".git")):
                return cls.real_or_self(directory)
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent
        return cls.real_or_self(env.get("CLAUDE_PROJECT_DIR") or cwd)

    @staticmethod
    def inside(root: str, real: str) -> bool:
        return real == root or real.startswith(root if root.endswith("/") else f"{root}/")

    @classmethod
    def rel_path(cls, root: str, path: str) -> str:
        real = cls.real_or_self(path)
        if cls.inside(root, real):
            return real[len(root) + 1 :] or "."
        if cls.inside(root, path):
            return path[len(root) + 1 :] or "."
        return path

    @staticmethod
    def glob_to_regexp(glob: str) -> re.Pattern:
        """A small glob matcher for `**/`, `**`, `*` and `?`; every other character is literal. Anchored."""
        any_char = "[^\\n\\r\\u2028\\u2029]"
        out = ""
        i = 0
        n = len(glob)
        while i < n:
            c = glob[i]
            if c == "*" and i + 1 < n and glob[i + 1] == "*":
                if i + 2 < n and glob[i + 2] == "/":
                    out += f"(?:{any_char}*/)?"
                    i += 2
                else:
                    out += f"{any_char}*"
                    i += 1
            elif c == "*":
                out += "[^/]*"
            elif c == "?":
                out += "[^/]"
            else:
                out += re.escape(c)
            i += 1
        return re.compile(rf"\A{out}\Z")

    @classmethod
    def is_exempt_path(cls, rel: str, rules: Rules) -> bool:
        return any(cls.glob_to_regexp(g).search(rel) for g in rules.get("scriptScanExempt") or [])
