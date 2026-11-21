"""PR watcher for a finished /ticket run.

Polls the run's pull request until there is something for the ticket session to do,
then prints one JSON line and exits (`watch_pr.py --state <abs>/<ticketsDir>/<KEY>/state.json`).

Outcomes: feedback, merged, closed (exit 0: the JSON line says which, and Claude Code
reports any non-zero exit of a background command as a failure), error (exit 1),
usage (exit 2). stdout carries the final JSON line only; progress and errors go to
stderr. Only `gh` is run. Every poll writes a heartbeat into state.json
(`watch: {pid, startedAt, heartbeatAt}`), and nothing else in that file.
"""

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

POLL_MS = 60_000
MAX_GH_FAILURES = 5
MARKER = "<!-- gated-dev -->"
"""Marks the pipeline's own PR replies, so they never count as feedback."""

EXIT = {"feedback": 0, "merged": 0, "closed": 0, "error": 1, "usage": 2}

_PR_URL = re.compile(r"^https?://[^/]+/([^/]+)/([^/]+)/pull/(\d+)")


def default_run(cmd: str, args: list[str], *, cwd: str | None = None) -> str:
    try:
        proc = subprocess.run([cmd, *args], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as error:
        raise RuntimeError(f"{cmd} {' '.join(args)} failed: {error}") from error
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit status {proc.returncode}"
        raise RuntimeError(f"{cmd} {' '.join(args)} failed: {detail}")
    return proc.stdout


def _default_sleep(ms: int) -> None:
    time.sleep(ms / 1000)


def _default_log(line: str) -> None:
    sys.stderr.write(f"{line}\n")


def _iso(moment: datetime) -> str:
    """ISO 8601 UTC with milliseconds and `Z`, as JS `toISOString()`."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _time(value: Any) -> float | None:
    """Epoch seconds of an ISO timestamp, None when absent or unparsable (JS `Date.parse` -> NaN)."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def parse_pr_url(url: Any) -> dict | None:
    match = _PR_URL.match(url) if isinstance(url, str) else None
    if not match:
        return None
    return {"owner": match[1], "repo": match[2], "number": int(match[3])}


def _author(item: Mapping) -> str:
    author = item.get("author")
    login = author.get("login") if isinstance(author, Mapping) else None
    return login or ""


def normalize_pr(view: Mapping, inline: Iterable[Mapping] = ()) -> dict:
    """Merges `gh pr view` JSON and inline comments into `{state, mergedAt, createdAt, feedback}`."""
    feedback = [
        {
            "login": _author(r),
            "body": r.get("body") or "",
            "state": r.get("state") or "",
            "createdAt": r.get("submittedAt") or r.get("createdAt"),
        }
        for r in view.get("reviews") or []
    ]
    feedback += [
        {"login": _author(c), "body": c.get("body") or "", "createdAt": c.get("createdAt")}
        for c in view.get("comments") or []
    ]
    feedback += [
        {"login": c.get("login") or "", "body": c.get("body") or "", "createdAt": c.get("createdAt")}
        for c in inline
    ]
    return {
        "state": view.get("state"),
        "mergedAt": view.get("mergedAt"),
        "createdAt": view.get("createdAt"),
        "feedback": feedback,
    }


def fetch_pr(url: str, run: Callable[..., str] = default_run, cwd: str | None = None) -> dict:
    ref = parse_pr_url(url)
    if ref is None:
        raise ValueError(f"cannot parse PR url {url}")
    cwd = cwd if cwd is not None else os.getcwd()
    view = json.loads(run("gh", ["pr", "view", url, "--json", "state,mergedAt,createdAt,reviews,comments"], cwd=cwd))
    out = run(
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
    return normalize_pr(view, inline)


def newest_feedback_at(items: Iterable[Mapping] | None, cutoff: Any) -> str | None:
    """Newest human feedback after the cutoff, or None.

    Items are `{login, body, state?, createdAt}`. Feedback: author not a bot, body without
    the marker, created after the cutoff; a review counts when it has a body or requests
    changes, a comment when it has a body. An unparsable cutoff counts everything.
    """
    parsed_cutoff = _time(cutoff)
    after = parsed_cutoff if parsed_cutoff is not None else float("-inf")
    newest: str | None = None
    newest_at = float("-inf")
    for item in items or []:
        if (item.get("login") or "").endswith("[bot]"):
            continue
        body = item.get("body") or ""
        if MARKER in body:
            continue
        has_body = body.strip() != ""
        if item.get("state") is not None:
            if not has_body and item["state"] != "CHANGES_REQUESTED":
                continue
        elif not has_body:
            continue
        at = _time(item.get("createdAt"))
        if at is None or at <= after:
            continue
        if newest is None or at > newest_at:
            newest, newest_at = item["createdAt"], at
    return newest


def new_feedback_at(pr: Mapping | None, last_addressed: Any) -> str | None:
    """Cutoff: the last addressed comment, else the PR creation time."""
    pr = pr or {}
    return newest_feedback_at(pr.get("feedback"), last_addressed if last_addressed is not None else pr.get("createdAt"))


def _read_state(state_path: str) -> dict:
    try:
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError) as error:
        raise RuntimeError(f"cannot read {state_path}: {error}") from error
    if not isinstance(state, dict):
        raise TypeError(f"{state_path} is not a state object")
    if not isinstance(state.get("prUrl"), str) or state["prUrl"] == "":
        raise RuntimeError(f"{state_path} has no prUrl")
    return state


def _write_heartbeat(state_path: str, watch_field: dict, pid: int) -> None:
    """Read-modify-write of state.json: only `watch` changes, atomically."""
    with open(state_path, encoding="utf-8") as handle:
        state = json.load(handle)
    tmp = f"{state_path}.{pid}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({**state, "watch": watch_field}, indent=2) + "\n")
    os.replace(tmp, state_path)


def watch(
    *,
    state_path: str,
    run: Callable[..., str] = default_run,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[int], None] = _default_sleep,
    log: Callable[[str], None] = _default_log,
    pid: int | None = None,
) -> dict:
    """Polls until feedback, merge, close or MAX_GH_FAILURES failures in a row.

    Returns {outcome, prUrl, newestAt?, message?, at}.
    """
    pid = pid if pid is not None else os.getpid()
    started_at = _iso(now())
    failures = 0
    pr_url: str | None = None

    def done(outcome: str, **extra: str) -> dict:
        return {"outcome": outcome, "prUrl": pr_url, **extra, "at": _iso(now())}

    while True:
        pr: dict = {}
        state: dict = {}
        failure: Exception | None = None
        try:
            state = _read_state(state_path)
            pr_url = state["prUrl"]
            pr = fetch_pr(pr_url, run, os.path.dirname(state_path))
        except Exception as error:  # noqa: BLE001 - any failed poll counts, as in the JS watcher
            failure = error

        # The watcher is alive even when the poll failed.
        try:
            _write_heartbeat(state_path, {"pid": pid, "startedAt": started_at, "heartbeatAt": _iso(now())}, pid)
        except (OSError, ValueError) as error:
            log(f"heartbeat write failed: {error}")

        if failure is None:
            failures = 0
            if pr["state"] == "MERGED":
                return done("merged")
            if pr["state"] == "CLOSED":
                return done("closed")
            newest_at = new_feedback_at(pr, state.get("lastAddressedCommentAt"))
            if newest_at:
                return done("feedback", newestAt=newest_at)
        else:
            failures += 1
            log(f"poll failed ({failures}/{MAX_GH_FAILURES}): {failure}")
            if failures >= MAX_GH_FAILURES:
                return done("error", message=str(failure))
        sleep(POLL_MS)


def _parse_args(argv: list[str]) -> dict:
    if len(argv) != 2 or argv[0] != "--state":
        return {"error": "usage: watch_pr.py --state <abs path>/state.json"}
    if not os.path.isabs(argv[1]):
        return {"error": "--state must be an absolute path"}
    return {"state_path": argv[1]}


def main(argv: list[str] | None = None, **deps: Any) -> int:
    """Prints exactly one JSON line on stdout and returns the exit code."""
    out = deps.pop("out", None) or (lambda line: sys.stdout.write(f"{line}\n"))
    parsed = _parse_args(sys.argv[1:] if argv is None else argv)
    if "error" in parsed:
        out(json.dumps({"outcome": "usage", "message": parsed["error"]}))
        return EXIT["usage"]
    result = watch(state_path=parsed["state_path"], **deps)
    out(json.dumps(result))
    return EXIT[result["outcome"]]
