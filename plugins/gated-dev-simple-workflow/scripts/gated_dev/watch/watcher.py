"""PR watcher for a finished /ticket run.

Polls the run's pull request until there is something for the ticket session to do.
Every poll writes a heartbeat into state.json (`watch: {pid, startedAt, heartbeatAt}`),
and nothing else in that file. Only `gh` is run.
"""

import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime

from gated_dev.watch.feedback import FeedbackDetector
from gated_dev.watch.pr_client import PrClient


class PrWatcher:
    """Polls a pull request until feedback, merge, close or repeated gh failures."""

    POLL_MS = 60_000
    MAX_GH_FAILURES = 5
    MARKER = "<!-- gated-dev -->"
    """Marks the pipeline's own PR replies, so they never count as feedback."""

    @staticmethod
    def _default_sleep(ms: int) -> None:
        time.sleep(ms / 1000)

    @staticmethod
    def _default_log(line: str) -> None:
        sys.stderr.write(f"{line}\n")

    def __init__(
        self,
        run: Callable[..., str] = PrClient.default_run,
        sleep: Callable[[int], None] = _default_sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        log: Callable[[str], None] = _default_log,
    ) -> None:
        self.run = run
        self.sleep = sleep
        self.now = now
        self.log = log

    @staticmethod
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

    @staticmethod
    def _write_heartbeat(state_path: str, watch_field: dict, pid: int) -> None:
        """Read-modify-write of state.json: only `watch` changes, atomically."""
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)
        tmp = f"{state_path}.{pid}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({**state, "watch": watch_field}, indent=2) + "\n")
        os.replace(tmp, state_path)

    def watch(
        self,
        *,
        state_path: str,
        pid: int | None = None,
    ) -> dict:
        """Polls until feedback, merge, close or MAX_GH_FAILURES failures in a row.

        Returns {outcome, prUrl, newestAt?, message?, at}.
        """
        pid = pid if pid is not None else os.getpid()
        started_at = FeedbackDetector._iso(self.now())
        failures = 0
        pr_url: str | None = None

        def done(outcome: str, **extra: str) -> dict:
            return {"outcome": outcome, "prUrl": pr_url, **extra, "at": FeedbackDetector._iso(self.now())}

        while True:
            pr: dict = {}
            state: dict = {}
            failure: Exception | None = None
            try:
                state = self._read_state(state_path)
                pr_url = state["prUrl"]
                pr = PrClient(self.run).fetch_pr(pr_url, os.path.dirname(state_path))
            except Exception as error:  # noqa: BLE001 - any failed poll counts, as in the JS watcher
                failure = error

            # The watcher is alive even when the poll failed.
            try:
                self._write_heartbeat(
                    state_path,
                    {"pid": pid, "startedAt": started_at, "heartbeatAt": FeedbackDetector._iso(self.now())},
                    pid,
                )
            except (OSError, ValueError) as error:
                self.log(f"heartbeat write failed: {error}")

            if failure is None:
                failures = 0
                if pr["state"] == "MERGED":
                    return done("merged")
                if pr["state"] == "CLOSED":
                    return done("closed")
                newest_at = FeedbackDetector.new_feedback_at(pr, state.get("lastAddressedCommentAt"))
                if newest_at:
                    return done("feedback", newestAt=newest_at)
            else:
                failures += 1
                self.log(f"poll failed ({failures}/{self.MAX_GH_FAILURES}): {failure}")
                if failures >= self.MAX_GH_FAILURES:
                    return done("error", message=str(failure))
            self.sleep(self.POLL_MS)
