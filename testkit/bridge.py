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


def bridge(module: str, export: str, *args: Any) -> Any:
    proc = subprocess.run(
        ["node", str(BRIDGE), module, export],
        input=json.dumps(list(args)),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"bridge {module}.{export} exited {proc.returncode} with non-JSON stdout: {proc.stdout!r}\n{proc.stderr}"
        ) from None
    if isinstance(result, dict) and set(result) == {"$error"}:
        err = result["$error"]
        raise BridgeError(err["name"], err["message"])
    if proc.returncode != 0:
        raise RuntimeError(f"bridge {module}.{export} exited {proc.returncode}\n{proc.stderr}")
    return result
