"""The Orca CLI: repository registration and the worktree of a new ticket."""

import json
import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from gated_dev.errors import LaunchError
from gated_dev.launch.naming import LaunchNaming
from gated_dev.process import ProcessRunner


class OrcaWorktrees:
    """Runs the `orca` CLI for the repository at `root`: registration check and worktree creation."""

    def __init__(self, root: str | Path, run: ProcessRunner.Run = ProcessRunner.default_run) -> None:
        self.root = root
        self.run = run

    def orca_has_repo(self) -> bool:
        """True when Orca knows the repository at `root`."""
        try:
            self.run("orca", ["repo", "show", "--repo", f"path:{self.root}", "--json"])
        except LaunchError:
            return False
        return True

    def orca_worktree_args(self, *, key: str, title: str, base: str) -> list[str]:
        """The arguments of `orca worktree create` for a new ticket."""
        slug = LaunchNaming.slugify(title)
        return [
            "worktree",
            "create",
            "--repo",
            f"path:{self.root}",
            "--name",
            f"{key.lower()}-{slug}",
            "--branch",
            f"{key}/{slug}",
            "--base-branch",
            f"origin/{base}",
            "--setup",
            "skip",
            "--json",
        ]

    def create_orca_worktree(
        self,
        *,
        key: str,
        ticket: Mapping,
        config: Mapping,
        base: str,
        log: Callable[[str], None] = lambda line: None,
    ) -> dict:
        """Creates the ticket's worktree through Orca, copies the local Claude settings and the ticket file into it.

        Returns `{id, path, branch, selector}`.
        """
        argv = self.orca_worktree_args(key=key, title=ticket["title"], base=base)
        stdout = self.run("orca", argv).stdout
        try:
            out = json.loads(stdout)
        except ValueError as error:
            raise LaunchError("orca worktree create printed no JSON") from error
        result = LaunchNaming._get(out, "result")
        wt = LaunchNaming._first(LaunchNaming._get(result, "worktree"), result, out)
        wt_id = LaunchNaming._get(wt, "id")
        wt_path = LaunchNaming._first(LaunchNaming._get(wt, "path"), LaunchNaming._get(LaunchNaming._get(wt, "git"), "path"))
        if not isinstance(wt_path, str) or not os.path.isabs(wt_path):
            raise LaunchError("orca worktree create returned no worktree path")

        def copy(source: str | Path, target: Path, what: str) -> None:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            except OSError:
                # Path only: the settings file may hold permissions or secrets.
                log(f"{key}: could not copy {what} to {target}")

        settings = Path(self.root) / ".claude" / "settings.local.json"
        if settings.exists():
            copy(settings, Path(wt_path) / ".claude" / "settings.local.json", "settings.local.json")
        # The session reads the ticket from its own checkout; the base branch may not carry it.
        ticket_target = Path(wt_path) / config["ticketsDir"] / key / "ticket.md"
        if not ticket_target.exists():
            copy(ticket["file"], ticket_target, "ticket.md")
        return {
            "id": wt_id,
            "path": wt_path,
            "branch": argv[argv.index("--branch") + 1],
            "selector": f"id:{wt_id}" if wt_id else f"path:{wt_path}",
        }
