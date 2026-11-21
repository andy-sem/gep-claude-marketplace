"""Runs child processes for the launcher."""

import json
import subprocess
from collections.abc import Callable
from typing import Any

from gated_dev.completed_run import CompletedRun
from gated_dev.errors import LaunchError
from gated_dev.launch.naming import LaunchNaming

Run = Callable[[str, list[str]], CompletedRun]


class ProcessRunner:
    """Default process runner and the helpers that read its output."""

    Run = Run

    @staticmethod
    def default_run(file: str, argv: list[str]) -> CompletedRun:
        try:
            proc = subprocess.run([file, *argv], capture_output=True, text=True, check=False)
        except OSError as error:
            raise LaunchError(f"{file} failed: {error}") from error
        if proc.returncode != 0:
            # The orca CLI reports errors as JSON on stdout.
            detail = (proc.stderr or proc.stdout or f"exit status {proc.returncode}").strip()
            raise LaunchError(f"{file} failed: {detail}")
        return CompletedRun(proc.stdout, proc.stderr)

    @staticmethod
    def _terminal_handle(stdout: Any) -> str | None:
        """The terminal handle in the JSON `orca terminal create` prints, or None."""
        try:
            out = json.loads(stdout)
        except (TypeError, ValueError):
            return None
        result = LaunchNaming._get(out, "result")
        return LaunchNaming._first(
            LaunchNaming._get(LaunchNaming._get(result, "terminal"), "handle"),
            LaunchNaming._get(result, "handle"),
            LaunchNaming._get(out, "handle"),
        )
