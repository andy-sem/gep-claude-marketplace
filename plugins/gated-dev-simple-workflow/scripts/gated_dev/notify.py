"""Notification hook: a desktop notification when a /ticket session needs the user.

Hook mode (no arguments): for sessions started by the launcher (TICKET_FLOW_KEY set);
the event JSON on stdin supplies the message. Direct mode (`<title> <message>`): the
/ticket skill, e.g. after a merge; needs no TICKET_FLOW_KEY. macOS uses osascript,
Linux notify-send when installed, other systems stay silent. GATED_DEV_NOTIFY=0
turns it off. Never fails, never blocks: every path returns 0 without output.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import BinaryIO

DEFAULT_MESSAGE = "Claude needs your attention"

_OSASCRIPT = (
    "-e", "on run argv",
    "-e", 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"',
    "-e", "end run",
)  # fmt: skip


def _message(stdin: BinaryIO) -> str:
    """`message`, else `title`, of the event JSON; the default text when absent or unreadable."""
    try:
        event = json.loads(stdin.read().decode("utf-8"))
        text = event.get("message") or event.get("title")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_MESSAGE
    return text if isinstance(text, str) and text else DEFAULT_MESSAGE


def _os_name(env: Mapping[str, str]) -> str:
    """`uname -s` through PATH, as the shell hook did (tests fake the OS this way)."""
    try:
        out = subprocess.run(["uname", "-s"], capture_output=True, text=True, env=dict(env), check=False)
    except (OSError, ValueError):
        return ""
    return out.stdout.strip()


def _run(command: list[str], env: Mapping[str, str]) -> None:
    try:
        subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, env=dict(env), check=False)
    except (OSError, ValueError):
        pass


def _notify(title: str, message: str, env: Mapping[str, str]) -> None:
    path = env.get("PATH")
    match _os_name(env):
        case "Darwin":
            if tool := shutil.which("osascript", path=path):
                _run([tool, *_OSASCRIPT, "--", title, message], env)
        case "Linux":
            if tool := shutil.which("notify-send", path=path):
                _run([tool, "--", title, message], env)


def main(argv: Sequence[str] | None = None, stdin: BinaryIO | None = None, env: Mapping[str, str] | None = None) -> int:
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        env = os.environ if env is None else env
        if env.get("GATED_DEV_NOTIFY", "1") == "0":
            return 0
        if len(args) >= 2:
            title, message = args[0], args[1]
        else:
            key = env.get("TICKET_FLOW_KEY", "")
            if not key:
                return 0
            title = f"{key} needs you"
            message = _message(sys.stdin.buffer if stdin is None else stdin)
        _notify(title, message, env)
    except Exception:  # noqa: BLE001, S110  best-effort: a notification must never break the session
        pass
    return 0
