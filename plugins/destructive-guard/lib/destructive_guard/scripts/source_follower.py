"""Following `source` and relative imports from one script to the next."""

import os
import re
import stat
from typing import ClassVar

from .project_paths import ProjectPaths
from .run_targets import RunTargetResolver


class SourceFollower:
    """Finds the files a script pulls in and reads their heads."""

    MAX_FILE_BYTES = 65536

    JS_EXT = re.compile(r"\.(?:[cm]?[jt]s|[jt]sx)\Z")
    SHELL_EXT = re.compile(r"\.(?:sh|bash|zsh)\Z")

    _SCRIPT_DIR_RES: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"""\"?\$\(\s*dirname\s+\"?\$\{?(?:0|BASH_SOURCE(?:\[0\])?)\}?\"?\s*\)\"?""", re.ASCII),
        re.compile(r"\$\{(?:BASH_SOURCE(?:\[0\])?|0)%/\*\}", re.ASCII),
        re.compile(r"\$\{?(?:SCRIPT_DIR|SCRIPTDIR|HERE|DIR)\}?", re.ASCII),
    ]
    _ROOT_DIR_RE = re.compile(r"\$\{?(?:REPO_ROOT|ROOT_DIR|PROJECT_ROOT)\}?", re.ASCII)
    _SOURCE_RE = re.compile(r"(?:^|[;&|({]|\bthen\b|\bdo\b|\belse\b)[ \t]*(?:source|\.)[ \t]+([^\n]+)", re.MULTILINE | re.ASCII)
    _ARG_END = re.compile(r"[\s;&|)]")

    @classmethod
    def source_targets(cls, content: str, script_dir: str, cwd: str | None, root: str) -> list[dict]:
        out = []
        for m in cls._SOURCE_RE.finditer(content):
            arg = m.group(1)
            for sd in cls._SCRIPT_DIR_RES:
                arg = sd.sub("\u0001", arg)
            arg = cls._ROOT_DIR_RE.sub("\u0002", arg)
            arg = arg.replace('"', "").replace("'", "")
            arg = cls._ARG_END.split(arg)[0]
            if not arg or RunTargetResolver.unresolvable(arg.replace("\u0001", "").replace("\u0002", "")):
                continue
            if arg.startswith("\u0001"):
                arg = ProjectPaths._join(script_dir, arg[1:])
            elif arg.startswith("\u0002"):
                arg = ProjectPaths._join(root, arg[1:])
            elif not os.path.isabs(arg):
                if not cwd:
                    continue
                arg = ProjectPaths._resolve(cwd, arg)
            if "\u0001" not in arg and "\u0002" not in arg:
                out.append({"path": arg})
        return out

    _IMPORT_RES: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"""\b(?:import|export)\b[^'"`;]*?\bfrom\s*(['"])([^'"\n]+)\1""", re.ASCII),
        re.compile(r"""\bimport\s*(['"])([^'"\n]+)\1""", re.ASCII),
        re.compile(r"""\b(?:import|require)\s*\(\s*(['"])([^'"\n]+)\1\s*\)""", re.ASCII),
    ]
    _TRY_EXT: ClassVar[list[str]] = [".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx", ".jsx"]
    _EXT_SWAP: ClassVar[dict[str, str]] = {".js": ".ts", ".mjs": ".mts", ".cjs": ".cts", ".jsx": ".tsx"}

    @staticmethod
    def is_file(path: str) -> bool:
        try:
            return stat.S_ISREG(os.stat(path).st_mode)
        except (OSError, ValueError):
            return False

    @classmethod
    def resolve_import(cls, directory: str, spec: str) -> str:
        base = ProjectPaths._resolve(directory, spec)
        candidates = [base]
        ext = os.path.splitext(base)[1]
        if ext in cls._EXT_SWAP:
            candidates.append(base[: -len(ext)] + cls._EXT_SWAP[ext])
        candidates.extend(base + e for e in cls._TRY_EXT)
        candidates.extend(ProjectPaths._join(base, f"index{e}") for e in cls._TRY_EXT)
        return next((c for c in candidates if cls.is_file(c)), base)

    @classmethod
    def import_targets(cls, content: str, directory: str) -> list[dict]:
        found = []
        for rx in cls._IMPORT_RES:
            for m in rx.finditer(content):
                spec = m.group(2)
                if spec.startswith(("./", "../")):
                    found.append((m.start(), spec))
        found.sort(key=lambda f: f[0])  # source order, whichever pattern matched
        return [{"path": cls.resolve_import(directory, spec)} for _, spec in found]

    _SHEBANG = re.compile(r"#!\s*(\S+)(?:\s+(\S+))?")
    _JS_PROGRAMS = frozenset({"node", "tsx", "deno", "bun"})

    @classmethod
    def kind_of(cls, path: str, content: str) -> str:
        if cls.JS_EXT.search(path):
            return "js"
        if cls.SHELL_EXT.search(path):
            return "shell"
        shebang = cls._SHEBANG.match(content)
        if shebang:
            first = shebang.group(1)
            prog = ProjectPaths._basename(shebang.group(2) or "" if ProjectPaths._basename(first) == "env" else first)
            if prog in RunTargetResolver.SHELLS:
                return "shell"
            if prog in cls._JS_PROGRAMS:
                return "js"
            return "other"
        return "shell" if os.path.splitext(path)[1] == "" else "other"

    @classmethod
    def read_head(cls, real: str, size: int) -> str:
        with open(real, "rb") as f:
            data = f.read(min(size, cls.MAX_FILE_BYTES))
        return data.decode("utf-8", errors="replace")
