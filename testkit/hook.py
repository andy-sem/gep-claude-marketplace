"""Run the gate hook (gate.sh) as Claude Code does: JSON on stdin, decision on stdout."""

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .envs import clean_env
from .impl import Impl

ASK_TEMPLATE = (
    '{{"hookSpecificOutput":{{"hookEventName":"PreToolUse","permissionDecision":"ask",'
    '"permissionDecisionReason":"{}"}}}}'
)


def bash_input(command: str, cwd: Path | str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})


def mcp_input(tool: str, tool_input: dict, cwd: Path | str) -> str:
    return json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)})


@dataclass(frozen=True)
class HookResult:
    status: int
    stdout: str


def run_hook(
    impl: Impl,
    stdin: str | bytes,
    *env: Mapping[str, str],
    cwd: Path | str | None = None,
    timeout: float = 30,
) -> HookResult:
    data = stdin.encode() if isinstance(stdin, str) else stdin
    proc = subprocess.run(
        impl.gate_hook(),
        input=data,
        capture_output=True,
        env=clean_env(impl.env(), {"GATE_JEV": "", "GATE_JEV_LOG": ""}, *env),
        cwd=cwd,
        timeout=timeout,
        check=False,
    )
    return HookResult(proc.returncode, proc.stdout.decode("utf-8", errors="replace"))


def decision(stdout: str) -> dict:
    return json.loads(stdout)["hookSpecificOutput"]
