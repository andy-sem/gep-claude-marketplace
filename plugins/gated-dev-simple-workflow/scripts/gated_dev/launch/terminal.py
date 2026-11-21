"""Terminal-host detection and the commands that open a session tab."""

import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

from gated_dev.errors import LaunchError
from gated_dev.launch.naming import LaunchNaming


class TerminalCommands:
    """Detects the terminal host and builds the shell, AppleScript and Orca commands."""

    @staticmethod
    def detect_host(env: Mapping[str, str] | None = None) -> str | None:
        """The terminal app the launcher runs in, which is where its sessions open.

        `orca`, `iterm`, or None for anything else. Same rule as section 0 of the ticket skill:
        TERM_PROGRAM decides first, because a terminal started from another one can inherit its
        variables; ORCA_TERMINAL_HANDLE and ITERM_SESSION_ID cover a multiplexer such as tmux.
        """
        env = os.environ if env is None else env
        if env.get("TERM_PROGRAM") == "iTerm.app":
            return "iterm"
        if env.get("TERM_PROGRAM") == "Orca":
            return "orca"
        if env.get("ORCA_TERMINAL_HANDLE"):
            return "orca"
        if env.get("ITERM_SESSION_ID"):
            return "iterm"
        return None

    @staticmethod
    def iterm_session_id(env: Mapping[str, str] | None = None) -> str | None:
        """The GUID in ITERM_SESSION_ID ("w0t1p0:<GUID>"), or None if there is none."""
        env = os.environ if env is None else env
        match = re.fullmatch(r"[^:]*:([0-9A-Za-z-]+)", env.get("ITERM_SESSION_ID") or "")
        return match[1] if match else None

    @staticmethod
    def build_shell_command(*, cwd: Any, key: Any, args: Sequence[str] = (), remote_control: Any = False, summary: Any = None) -> str:
        if not LaunchNaming.is_safe_key(key):
            raise LaunchError(f"Invalid ticket key: {LaunchNaming._json(key)}")
        if not isinstance(cwd, str) or not os.path.isabs(cwd) or re.search(r"[\n\r\0]", cwd):
            raise LaunchError(f"cwd must be an absolute path: {LaunchNaming._json(cwd)}")
        # Imported here: cli imports the launcher, which imports this module.
        from gated_dev.launch.cli import LaunchCli

        for arg in args:
            if arg not in LaunchCli.ALLOWED_ARGS:
                raise LaunchError(f"Argument not allowed: {LaunchNaming._json(arg)}")
        if not isinstance(remote_control, bool):
            raise LaunchError(f"remoteControl must be a boolean: {LaunchNaming._json(remote_control)}")
        prompt = " ".join(["/ticket", key, *args])
        # The title only holds a checked key, a fixed purpose word and a summary reduced to a safe
        # character set, so double quotes are safe. The flags go before the prompt so the prompt
        # stays positional.
        title = LaunchNaming.session_name(key=key, args=args, summary=summary)
        rc = f'--remote-control "{title}" ' if remote_control else ""
        return f'cd {LaunchNaming.shell_quote(cwd)} && TICKET_FLOW_KEY={key} claude --name "{title}" {rc}"{prompt}"'

    @staticmethod
    def build_apple_script(*, command: str, key: str, args: Sequence[str] = (), session_id: str | None = None, summary: Any = None) -> str:
        name = LaunchNaming.session_name(key=key, args=args, summary=summary)
        # Without a match, for example after the launcher's tab was closed, the tab goes to the
        # frontmost window.
        find_window = (
            [
                "\trepeat with w in windows",
                "\t\trepeat with t in tabs of w",
                "\t\t\trepeat with s in sessions of t",
                f"\t\t\t\tif id of s is {LaunchNaming.apple_script_string(session_id)} then",
                "\t\t\t\t\tset targetId to id of w",
                "\t\t\t\t\tset targetWindow to first window whose id is targetId",
                "\t\t\t\tend if",
                "\t\t\tend repeat",
                "\t\tend repeat",
                "\tend repeat",
            ]
            if session_id
            else []
        )
        return "\n".join(
            [
                'tell application "iTerm2"',
                "\tactivate",
                "\tset targetWindow to missing value",
                *find_window,
                "\tif targetWindow is missing value and (count of windows) > 0 then",
                "\t\tset targetWindow to current window",
                "\tend if",
                "\tif targetWindow is missing value then",
                "\t\tcreate window with default profile",
                "\t\ttell current session of current window",
                f"\t\t\tset name to {LaunchNaming.apple_script_string(name)}",
                f"\t\t\twrite text {LaunchNaming.apple_script_string(command)}",
                "\t\tend tell",
                "\telse",
                "\t\ttell targetWindow",
                "\t\t\tcreate tab with default profile",
                "\t\t\ttell current session",
                f"\t\t\t\tset name to {LaunchNaming.apple_script_string(name)}",
                f"\t\t\t\twrite text {LaunchNaming.apple_script_string(command)}",
                "\t\t\tend tell",
                "\t\tend tell",
                "\tend if",
                "end tell",
            ]
        )

    @staticmethod
    def build_orca_args(
        *,
        cwd: str,
        command: str,
        key: str,
        args: Sequence[str] = (),
        workspace_id: str | None = None,
        selector: str | None = None,
        summary: Any = None,
    ) -> list[str]:
        """`selector` names the Orca worktree the tab opens in.

        Without it, `workspace_id` (ORCA_WORKTREE_ID) keeps the tab next to the launcher. The
        session still runs in `cwd`, because the command starts with a cd.
        """
        return [
            "terminal",
            "create",
            "--worktree",
            selector or (f"id:{workspace_id}" if workspace_id else f"path:{cwd}"),
            "--title",
            LaunchNaming.session_name(key=key, args=args, summary=summary),
            "--command",
            command,
            "--json",
        ]
