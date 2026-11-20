"""Call exports of the JS destructive-guard lib from Python tests (until the JS is removed)."""

import json
import subprocess
from pathlib import Path
from typing import Any

BRIDGE = Path(__file__).resolve().parent / "_bridge.mjs"


class BridgeError(Exception):
    """A JS exception, carried over with its error name."""

    def __init__(self, name: str, message: str):
        super().__init__(f"{name}: {message}")
        self.name = name
        self.message = message


def _decode(returncode: int, stdout: str, stderr: str, what: str) -> Any:
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"bridge {what} exited {returncode} with non-JSON stdout: {stdout!r}\n{stderr}") from None
    if returncode == 1 and isinstance(result, dict) and set(result) == {"$error"}:
        err = result["$error"]
        raise BridgeError(err["name"], err["message"])
    if returncode != 0:
        raise RuntimeError(f"bridge {what} exited {returncode}\n{stderr}")
    return result


def bridge(module: str, export: str, *args: Any) -> Any:
    try:
        proc = subprocess.run(
            ["node", str(BRIDGE), module, export],
            input=json.dumps(list(args)),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError("node not found on PATH") from None
    return _decode(proc.returncode, proc.stdout, proc.stderr, f"{module}.{export}")
