"""Opens the session tab for a ticket."""

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from gated_dev.errors import LaunchError
from gated_dev.launch.naming import LaunchNaming
from gated_dev.launch.orca import OrcaWorktrees
from gated_dev.launch.terminal import TerminalCommands
from gated_dev.launch.ticket_project import TicketProject
from gated_dev.process import ProcessRunner


class TicketLauncher:
    """Plans and opens one Claude Code session tab per ticket."""

    @staticmethod
    def launch_tab(
        *,
        host: str | None,
        cwd: str,
        key: str,
        args: Sequence[str] = (),
        remote_control: bool = False,
        summary: Any = None,
        selector: str | None = None,
        env: Mapping[str, str] | None = None,
        run: ProcessRunner.Run = ProcessRunner.default_run,
        log: Callable[[str], None] = lambda line: None,
    ) -> dict:
        """Opens one tab running the session command.

        `host` is `orca` or `iterm`; `selector` is the Orca worktree to open the tab in (Orca only).
        Returns `{command, title}`.
        """
        env = os.environ if env is None else env
        title = LaunchNaming.session_name(key=key, args=args, summary=summary)
        command = TerminalCommands.build_shell_command(cwd=cwd, key=key, args=args, remote_control=remote_control, summary=summary)
        if host == "orca":
            created = run(
                "orca",
                TerminalCommands.build_orca_args(
                    cwd=cwd,
                    command=command,
                    key=key,
                    args=args,
                    workspace_id=env.get("ORCA_WORKTREE_ID"),
                    selector=selector,
                    summary=summary,
                ),
            )
            # Orca retitles a tab that runs Claude, so set the title once more.
            handle = ProcessRunner._terminal_handle(created.stdout if created else None)
            if handle:
                try:
                    run("orca", ["terminal", "rename", "--terminal", handle, "--title", title])
                except LaunchError as error:
                    log(f"{key}: could not rename the tab ({error})")
        elif host == "iterm":
            script = TerminalCommands.build_apple_script(command=command, key=key, args=args, session_id=TerminalCommands.iterm_session_id(env), summary=summary)
            run("osascript", [part for line in script.split("\n") for part in ("-e", line)])
        else:
            raise LaunchError(f"unknown host {LaunchNaming._json(host)}")
        return {"command": command, "title": title}

    @classmethod
    def launch_ticket(
        cls,
        *,
        root: str | Path,
        key: str,
        config: Mapping,
        remote_control: bool = False,
        dry_run: bool = False,
        env: Mapping[str, str] | None = None,
        run: ProcessRunner.Run = ProcessRunner.default_run,
        log: Callable[[str], None] = lambda line: None,
    ) -> dict:
        """Plans and (unless `dry_run`) opens the session for one ticket.

        Returns `{key, mode, host, cwd, command, title, base, worktree, note, launched}` where
        `mode` is `resume`, `orca-worktree` or `main-checkout`. A dry run calls only read-only
        commands (`git worktree list`, `git symbolic-ref`, `orca repo show`).
        """
        env = os.environ if env is None else env
        root = str(root)
        TicketProject.check_key(key, config)
        host = TerminalCommands.detect_host(env)
        if not host and not dry_run:
            raise LaunchError(f"open sessions from Orca or iTerm2 (TERM_PROGRAM={env.get('TERM_PROGRAM', 'unset')}); --dry-run works anywhere")
        base: dict = {"key": key, "host": host, "base": None, "worktree": None, "note": None}

        def open_session(plan: dict) -> dict:
            result = {**base, **plan, "launched": False}
            result["title"] = LaunchNaming.session_name(key=key, args=plan["args"], summary=plan["summary"])
            result["command"] = TerminalCommands.build_shell_command(
                cwd=plan["cwd"], key=key, args=plan["args"], remote_control=remote_control, summary=plan["summary"]
            )
            if dry_run:
                return result
            TicketLauncher.launch_tab(
                host=host,
                cwd=plan["cwd"],
                key=key,
                args=plan["args"],
                remote_control=remote_control,
                summary=plan["summary"],
                selector=plan.get("selector"),
                env=env,
                run=run,
                log=log,
            )
            return {**result, "launched": True}

        existing = TicketProject(root, run).find_run(key=key, config=config)
        if existing:
            summary = None
            try:
                summary = TicketProject(existing["path"]).read_ticket(key=key, config=config)["title"]
            except (LaunchError, OSError, ValueError):
                pass
            return open_session(
                {
                    "mode": "resume",
                    "cwd": existing["path"],
                    "args": ["--resume"],
                    "summary": summary,
                    "note": "run is done; resuming restarts the PR watch" if existing["stage"] == "done" else None,
                    "worktree": existing,
                    "selector": f"path:{existing['path']}",
                }
            )

        # Without a ticket.md, the session's intake writes it (from the tracker or from the project
        # rules), and it decides title and base: start in the main checkout and let the session create
        # the worktree. Without a tracker or rules, read_ticket raises the "no ticket file" error.
        if not (Path(root) / config["ticketsDir"] / key / "ticket.md").exists():
            if config["tracker"]:
                note = "no ticket.md yet; the session fetches it from Jira"
            elif config["orchestratorRules"]:
                note = "no ticket.md yet; the session's intake rules write it"
            else:
                note = None
            if note:
                return open_session({"mode": "main-checkout", "cwd": root, "args": [], "summary": None, "note": note})
        ticket = TicketProject(root).read_ticket(key=key, config=config)
        summary = ticket["title"]

        def main_checkout(note: str | None) -> dict:
            return open_session({"mode": "main-checkout", "cwd": root, "args": [], "summary": summary, "note": note})

        if host != "orca":
            return main_checkout(None)
        if not OrcaWorktrees(root, run).orca_has_repo():
            return main_checkout(f"{root} is not an Orca repo; the skill creates a git worktree")

        branch_base = TicketProject(root, run).resolve_base(ticket=ticket, config=config)
        if dry_run:
            argv = OrcaWorktrees(root, run).orca_worktree_args(key=key, title=ticket["title"], base=branch_base)
            planned = " ".join(a if LaunchNaming._PLAIN_ARG.fullmatch(a) else LaunchNaming.shell_quote(a) for a in argv)
            return {
                **base,
                "mode": "orca-worktree",
                "base": branch_base,
                "cwd": f"<new Orca worktree {argv[argv.index('--name') + 1]}>",
                "title": LaunchNaming.session_name(key=key, summary=summary),
                "command": f"orca {planned}",
                "note": f"then /ticket {key} in the new worktree",
                "launched": False,
            }
        run("git", ["-C", root, "fetch", "origin", branch_base])
        # A failure from here on must not fall back to the main checkout: the session would create
        # a second worktree.
        worktree = OrcaWorktrees(root, run).create_orca_worktree(key=key, ticket=ticket, config=config, base=branch_base, log=log)
        opened = open_session(
            {
                "mode": "orca-worktree",
                "cwd": worktree["path"],
                "args": [],
                "summary": summary,
                "worktree": worktree,
                "selector": worktree["selector"],
            }
        )
        return {**opened, "base": branch_base}
