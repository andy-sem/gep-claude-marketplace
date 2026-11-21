"""Where relative paths in GATE_* variables point (port of paths.mjs).

A hook runs in the session's current directory, which moves with every `cd`, so a
relative rules file, prompt file or log would break or scatter. They resolve against
the project instead: CLAUDE_PROJECT_DIR (set for hooks), else the nearest ancestor of
`cwd` with a `.git` entry (file or directory), else `cwd`. Absolute paths are kept as
they are: no symlink resolution.
"""

import os
from collections.abc import Mapping
from pathlib import Path


class ProjectDir:
    @staticmethod
    def project_dir(env: Mapping[str, str], cwd: str | Path) -> str:
        from_env = env.get("CLAUDE_PROJECT_DIR")
        from_env = from_env.strip() if isinstance(from_env, str) else ""
        if from_env:
            return os.path.abspath(from_env)
        start = os.path.abspath(cwd)
        directory = start
        while True:
            if os.path.exists(os.path.join(directory, ".git")):
                return directory
            parent = os.path.dirname(directory)
            if parent == directory:
                return start
            directory = parent

    @classmethod
    def project_path(cls, path: str, env: Mapping[str, str], cwd: str | Path) -> str:
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(cls.project_dir(env, cwd), path))
