"""Collecting the files a command runs and the files they pull in."""

import json
import os
import stat
from typing import Any

from ..rules.rule_loader import Rules
from .project_paths import ProjectPaths
from .run_targets import RunTargetResolver
from .source_follower import SourceFollower


class ScriptCollector:
    """Reads the project files a command runs, breadth-first."""

    MAX_FOLLOW_DEPTH = 3
    MAX_FILES = 32

    def __init__(self, rules: Rules, cwd: str, root: str) -> None:
        self.rules = rules
        self.cwd = cwd
        self.root = root

    def collect(self, command: str) -> dict[str, Any]:
        """Reads the files `command` runs and the files they pull in (breadth-first, in source order).
        Returns `{"files", "problems"}`:
        - files: `{path, content, size, truncated, exempt, depth}`, `path` relative to the project root
          (a package script is `<dir>/package.json#scripts.<name>`);
        - problems: `{path, reason, exempt}` for files the gate could not read safely.
        A missing file is skipped. An unparsable command gives nothing: the rule layer already asks."""
        files: list[dict] = []
        problems: list[dict] = []
        seen: set[str] = set()

        def queue_item(t: dict, depth: int, parent_exempt: bool, frm: str | None) -> dict:
            # the directory a target's own command ran in, else the one of the file it came from
            return {**t, "depth": depth, "parentExempt": parent_exempt, "cwd": t.get("cwd", frm)}

        queue = [queue_item(t, 0, False, self.cwd) for t in RunTargetResolver(self.rules, self.cwd, self.root).command_targets(command)]
        capped = False
        qi = 0
        while qi < len(queue):
            item = queue[qi]
            qi += 1
            try:
                real = os.path.realpath(item["path"], strict=True)
            except (FileNotFoundError, NotADirectoryError):
                continue
            except (OSError, ValueError):
                problems.append({"path": ProjectPaths.rel_path(self.root, item["path"]), "reason": "is unreadable", "exempt": item["parentExempt"]})
                continue
            script = item.get("script")
            key = f"{real}#{script}" if script else real
            if key in seen:
                continue
            seen.add(key)
            shown = f"{ProjectPaths.rel_path(self.root, item['path'])}#scripts.{script}" if script else ProjectPaths.rel_path(self.root, item["path"])
            exempt = item["parentExempt"] or item.get("context") is True or ProjectPaths.is_exempt_path(shown.split("#")[0], self.rules)

            def problem(reason: str, shown: str = shown, exempt: bool = exempt) -> None:
                problems.append({"path": shown, "reason": reason, "exempt": exempt})

            if not ProjectPaths.inside(self.root, real):
                problem("is outside the project")
                continue
            try:
                st = os.stat(real)
            except OSError:
                problem("is unreadable")
                continue
            if not stat.S_ISREG(st.st_mode):
                problem("is not a regular file")
                continue
            if len(files) >= ScriptCollector.MAX_FILES:
                if not capped:
                    problems.append({"path": shown, "reason": f"more than {ScriptCollector.MAX_FILES} files", "exempt": False})
                capped = True
                break
            size = st.st_size
            truncated = False
            try:
                content = SourceFollower.read_head(real, st.st_size)
            except OSError:
                problem("is unreadable")
                continue
            if script:
                try:
                    with open(real, encoding="utf-8", errors="replace") as f:
                        parsed = json.loads(f.read())
                except (OSError, ValueError):
                    problem("is unreadable")
                    continue
                scripts = parsed.get("scripts") if isinstance(parsed, dict) else None
                body = scripts.get(script) if isinstance(scripts, dict) else None
                if not isinstance(body, str):
                    continue
                content = body
                size = len(body.encode("utf-8"))
            if size > SourceFollower.MAX_FILE_BYTES:
                truncated = True
                content = content[:SourceFollower.MAX_FILE_BYTES]
                problem("exceeds 64 KB")
            files.append(
                {"path": shown, "content": content, "size": size, "truncated": truncated, "exempt": exempt, "depth": item["depth"]}
            )

            if item["depth"] >= ScriptCollector.MAX_FOLLOW_DEPTH:
                continue
            directory = os.path.dirname(real)
            nxt: list[dict] = []
            if script:
                nxt = RunTargetResolver(self.rules, directory, self.root).command_targets(content)
            else:
                kind = SourceFollower.kind_of(real, content)
                if kind == "shell":
                    nxt = SourceFollower.source_targets(content, directory, item["cwd"], self.root)
                elif kind == "js":
                    nxt = SourceFollower.import_targets(content, directory)
            for t in nxt:
                queue.append(queue_item(t, item["depth"] + 1, exempt, item["cwd"]))
        return {"files": files, "problems": problems}
