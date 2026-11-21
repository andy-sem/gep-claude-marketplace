"""Real git repositories for contract tests, isolated from the developer's git configuration."""

import os
import subprocess
from pathlib import Path


class GitRepo:
    @staticmethod
    def git_env(home: Path) -> dict[str, str]:
        """Environment overlay: no global/system config (hooks, signing), fixed identity, no prompts."""
        return {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Test Author",
            "GIT_AUTHOR_EMAIL": "author@example.com",
            "GIT_COMMITTER_NAME": "Test Author",
            "GIT_COMMITTER_EMAIL": "author@example.com",
        }

    @classmethod
    def git(cls, cwd: Path, *args: str) -> str:
        env = {**os.environ, **cls.git_env(Path(cwd).parent)}
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr}")
        return proc.stdout

    @classmethod
    def init_repo(
        cls, path: Path, *, origin: Path | None = None, branch: str = "main"
    ) -> Path:
        """A repository with one commit on `branch`; with `origin`, a bare remote with origin/HEAD set.

        Returns the resolved path (what `git worktree list` prints).
        """
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        path = path.resolve()
        cls.git(path, "init", "-q", "-b", branch)
        (path / "README.md").write_text("# demo\n")
        cls.git(path, "add", "README.md")
        cls.git(path, "commit", "-q", "-m", "init")
        if origin is not None:
            origin = Path(origin)
            origin.mkdir(parents=True, exist_ok=True)
            cls.git(origin, "init", "-q", "--bare", "-b", branch)
            cls.git(path, "remote", "add", "origin", str(origin))
            cls.git(path, "push", "-q", "-u", "origin", branch)
            cls.git(path, "remote", "set-head", "origin", branch)
        return path

    @classmethod
    def add_worktree(cls, repo: Path, path: Path, branch: str) -> Path:
        """`git worktree add -b <branch> <path>`; returns the resolved worktree path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cls.git(repo, "worktree", "add", "-q", "-b", branch, str(path))
        return path.resolve()
