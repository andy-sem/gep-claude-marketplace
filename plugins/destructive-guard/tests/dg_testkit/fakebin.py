"""Recording fake binaries on a private PATH, so tests never reach a real gh, orca or osascript."""

import json
import os
import shutil
import stat
from pathlib import Path

from .pythons import Pythons


class FakeBin:
    """A directory of recording stubs. Use `.path` as the whole PATH of the process under test."""

    _STUB = """#!{python} -I
import json, os, sys
tmp = {tmp!r}
name = {name!r}
with open(os.path.join(tmp, name + ".json")) as handle:
    cfg = json.load(handle)
stdin = sys.stdin.read() if cfg.get("read_stdin") else None
files = {{}}
for p in cfg.get("snapshot", []):
    try:
        with open(p) as handle:
            files[p] = handle.read()
    except OSError:
        files[p] = None
record = {{"name": name, "argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": stdin, "files": files}}
with open(os.path.join(tmp, "calls.jsonl"), "a") as handle:
    handle.write(json.dumps(record) + "\\n")
entry = {{k: cfg.get(k) for k in ("stdout", "stderr", "status", "write")}}
script = cfg.get("script")
if script:
    counter = os.path.join(tmp, name + ".count")
    n = 0
    if os.path.exists(counter):
        with open(counter) as handle:
            n = int(handle.read())
    with open(counter, "w") as handle:
        handle.write(str(n + 1))
    entry.update(script[min(n, len(script) - 1)])
for route in cfg.get("routes", []):
    match = route["match"]
    if sys.argv[1 : 1 + len(match)] == match:
        entry.update({{k: v for k, v in route.items() if k != "match"}})
        break
for target, text in (entry.get("write") or {{}}).items():
    with open(target, "w") as handle:
        handle.write(text)
sys.stdout.write(entry.get("stdout") or "")
sys.stderr.write(entry.get("stderr") or "")
sys.stdout.flush()
sys.exit(entry.get("status") or 0)
"""

    def __init__(self, tmp: Path):
        self._tmp = Path(tmp)
        self.path = self._tmp / "bin"
        self.path.mkdir(parents=True, exist_ok=True)
        self._calls = self._tmp / "calls.jsonl"

    def add(
        self,
        name: str,
        *,
        stdout: str = "",
        stderr: str = "",
        status: int = 0,
        script: list[dict] | None = None,
        write: dict[str, str] | None = None,
        routes: list[dict] | None = None,
        snapshot: list[str] | None = None,
        read_stdin: bool = False,
    ) -> Path:
        """Write the stub `name`.

        Each call appends {"name", "argv", "cwd", "stdin", "files"} to calls.jsonl. `script` entries
        ({"stdout", "stderr", "status", "write"}) are consumed one per call, the last repeating; a route
        ({"match": [leading args], ...entry}) overrides the default and the script when the arguments
        start with `match`. `write` maps a path to text written on every call; `snapshot` paths are
        read at call time (before `write`) into the call's "files".
        """
        config = {
            "stdout": stdout,
            "stderr": stderr,
            "status": status,
            "script": script,
            "write": write,
            "routes": routes or [],
            "snapshot": snapshot or [],
            "read_stdin": read_stdin,
        }
        (self._tmp / f"{name}.json").write_text(json.dumps(config))
        stub = self.path / name
        stub.write_text(
            FakeBin._STUB.format(
                python=Pythons.require_new_python(os.environ),
                tmp=str(self._tmp),
                name=name,
            )
        )
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return stub

    def link(self, name: str) -> Path:
        """Symlink the real tool into the dir (FileNotFoundError when the machine has none)."""
        real = shutil.which(name)
        if real is None:
            raise FileNotFoundError(f"{name} not found on PATH")
        target = self.path / name
        target.symlink_to(real)
        return target

    def calls(self, name: str | None = None) -> list[dict]:
        if not self._calls.exists():
            return []
        rows = [
            json.loads(line) for line in self._calls.read_text().splitlines() if line
        ]
        return [r for r in rows if name is None or r["name"] == name]

    @staticmethod
    def absolute(cmd: list[str]) -> list[str]:
        """`cmd` with its program resolved on the developer's PATH, for a child whose PATH is only the fake dir."""
        program = shutil.which(cmd[0])
        if program is None:
            raise FileNotFoundError(f"{cmd[0]} not found on PATH")
        return [program, *cmd[1:]]
