"""Run the gate hook (gate.sh) as Claude Code does: JSON on stdin, decision on stdout."""

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

from .envs import IsolatedEnv
from .hook_result import HookResult
from .impl import Impl


class HookRunner:
    """Builds hook inputs, runs the gate hook and reads its decision."""

    ASK_TEMPLATE = (
        '{{"hookSpecificOutput":{{"hookEventName":"PreToolUse","permissionDecision":"ask",'
        '"permissionDecisionReason":"{}"}}}}'
    )

    @staticmethod
    def bash_input(command: str, cwd: Path | str) -> str:
        return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})

    @staticmethod
    def mcp_input(tool: str, tool_input: dict, cwd: Path | str) -> str:
        return json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)})

    @staticmethod
    def run(
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
            env=IsolatedEnv.clean(impl.env(), {"GATE_JEV": "", "GATE_JEV_LOG": ""}, *env),
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
        return HookResult(proc.returncode, proc.stdout.decode("utf-8", errors="replace"))

    @staticmethod
    def decision(stdout: str) -> dict:
        return json.loads(stdout)["hookSpecificOutput"]
