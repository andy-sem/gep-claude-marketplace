"""PR lookups through `gh` for the watcher."""

import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping
from typing import Any


class PrClient:
    """Reads a pull request through an injected `gh` runner."""

    def __init__(self, run: Callable[..., str]) -> None:
        self.run = run

    _PR_URL = re.compile(r"^https?://[^/]+/([^/]+)/([^/]+)/pull/(\d+)")

    @staticmethod
    def default_run(cmd: str, args: list[str], *, cwd: str | None = None) -> str:
        try:
            proc = subprocess.run([cmd, *args], cwd=cwd, capture_output=True, text=True, check=False)
        except OSError as error:
            raise RuntimeError(f"{cmd} {' '.join(args)} failed: {error}") from error
        if proc.returncode != 0:
            detail = proc.stderr.strip() or f"exit status {proc.returncode}"
            raise RuntimeError(f"{cmd} {' '.join(args)} failed: {detail}")
        return proc.stdout

    @classmethod
    def parse_pr_url(cls, url: Any) -> dict | None:
        match = cls._PR_URL.match(url) if isinstance(url, str) else None
        if not match:
            return None
        return {"owner": match[1], "repo": match[2], "number": int(match[3])}

    @staticmethod
    def _author(item: Mapping) -> str:
        author = item.get("author")
        login = author.get("login") if isinstance(author, Mapping) else None
        return login or ""

    @classmethod
    def normalize_pr(cls, view: Mapping, inline: Iterable[Mapping] = ()) -> dict:
        """Merges `gh pr view` JSON and inline comments into `{state, mergedAt, createdAt, feedback}`."""
        feedback = [
            {
                "login": cls._author(r),
                "body": r.get("body") or "",
                "state": r.get("state") or "",
                "createdAt": r.get("submittedAt") or r.get("createdAt"),
            }
            for r in view.get("reviews") or []
        ]
        feedback += [
            {
                "login": cls._author(c),
                "body": c.get("body") or "",
                "createdAt": c.get("createdAt"),
            }
            for c in view.get("comments") or []
        ]
        feedback += [
            {
                "login": c.get("login") or "",
                "body": c.get("body") or "",
                "createdAt": c.get("createdAt"),
            }
            for c in inline
        ]
        return {
            "state": view.get("state"),
            "mergedAt": view.get("mergedAt"),
            "createdAt": view.get("createdAt"),
            "feedback": feedback,
        }

    def fetch_pr(self, url: str, cwd: str | None = None) -> dict:
        ref = self.parse_pr_url(url)
        if ref is None:
            raise ValueError(f"cannot parse PR url {url}")
        cwd = cwd if cwd is not None else os.getcwd()
        view = json.loads(
            self.run("gh", ["pr", "view", url, "--json", "state,mergedAt,createdAt,reviews,comments"], cwd=cwd)
        )
        out = self.run(
            "gh",
            [
                "api",
                f"repos/{ref['owner']}/{ref['repo']}/pulls/{ref['number']}/comments",
                "--paginate",
                "--jq",
                ".[] | {login: .user.login, body: .body, createdAt: .created_at}",
            ],
            cwd=cwd,
        )
        inline = [json.loads(line) for line in out.split("\n") if line.strip()]
        return self.normalize_pr(view, inline)
