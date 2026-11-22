"""Run the check CLI (dry run of the gate) as a subprocess."""

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

from .envs import IsolatedEnv
from .impl import Impl


class CheckRunner:
    @staticmethod
    def run_check(
        impl: Impl, *args: str, env: Mapping[str, str] = {}, cwd: Path | str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*impl.check(), *args],
            capture_output=True,
            text=True,
            env=IsolatedEnv.clean(impl.env(), env),
            cwd=cwd,
            timeout=60,
            check=False,
        )


    @classmethod
    def check_call(cls, impl: Impl, call: dict, env: Mapping[str, str] = {}, cwd: Path | None = None) -> dict:
        """`call` is {"bash": cmd} or {"mcp": tool, "input": {...}}; returns the parsed --json result."""
        args = ["--json"]
        if "bash" in call:
            args += ["--", call["bash"]]
        else:
            args += ["--mcp", call["mcp"], json.dumps(call.get("input", {}))]
        proc = cls.run_check(impl, *args, env=env, cwd=cwd)
        assert proc.returncode == 0, f"check {args} exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        return json.loads(proc.stdout)
