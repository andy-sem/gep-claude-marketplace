"""Call exports of the JS destructive-guard lib from Python tests (until the JS is removed)."""

import json
import re
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


def call(module: str, export: str, *args: Any) -> dict:
    """A marker for a nested call: _bridge.mjs replaces it by the call's result before the outer call."""
    return {"$call": [module, export, list(args)]}


def bridge_many(calls: list[tuple[str, str, list]]) -> list[Any]:
    """Run several calls in one node process; results come back in order."""
    try:
        proc = subprocess.run(
            ["node", str(BRIDGE), "--batch"],
            input=json.dumps([[m, f, list(a)] for m, f, a in calls]),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError("node not found on PATH") from None
    return _decode(proc.returncode, proc.stdout, proc.stderr, "batch")


def js_regexp(value: dict) -> re.Pattern:
    """Turn a bridged JS RegExp ({"$regexp": source, "flags": flags}) into a Python pattern."""
    return re.compile(value["$regexp"], re.IGNORECASE if "i" in value.get("flags", "") else 0)
