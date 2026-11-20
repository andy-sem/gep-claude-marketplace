"""Run the check CLI (dry run of the gate) as a subprocess."""

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

from .envs import clean_env
from .impl import Impl


def run_check(
    impl: Impl, *args: str, env: Mapping[str, str] = {}, cwd: Path | str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*impl.check(), *args],
        capture_output=True,
        text=True,
        env=clean_env(impl.env(), env),
        cwd=cwd,
        timeout=60,
        check=False,
    )


def check_call(impl: Impl, call: dict, env: Mapping[str, str] = {}, cwd: Path | None = None) -> dict:
    """`call` is {"bash": cmd} or {"mcp": tool, "input": {...}}; returns the parsed --json result."""
    args = ["--json"]
    if cwd is not None:
        args += ["--cwd", str(cwd)]
    if "bash" in call:
        args += ["--", call["bash"]]
    else:
        args += ["--mcp", call["mcp"], json.dumps(call.get("input", {}))]
    proc = run_check(impl, *args, env=env, cwd=cwd)
    assert proc.returncode == 0, f"check {args} exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout)
