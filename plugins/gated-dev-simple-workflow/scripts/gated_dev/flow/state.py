"""Flow state of one Jira parent: a JSON file in the git common dir, with a lock."""

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gated_dev.errors import FlowError
from gated_dev.process import ProcessRunner

Clock = Callable[[], datetime]


class FlowState:
    """`<git-common-dir>/gated-dev/flow/<PARENT>.json`, shared by every worktree.

    `tickets` maps a key to `{status, summary, reason, launchedAt, worktree, stage, prUrl, relaunches,
    staleWarnedAt}` (skipped tickets: `{status, reason, at}`); `picks` keeps the last MAX_PICKS decisions.
    """

    VERSION = 1
    MAX_PICKS = 50
    STATUSES = frozenset(("launched", "merged", "aborted", "skipped"))

    @staticmethod
    def _default_now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _default_is_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, owned by another user
        return True

    @staticmethod
    def iso(moment: datetime) -> str:
        """ISO 8601 UTC with seconds and `Z`."""
        return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def flow_dir(*, root: str | Path, run: ProcessRunner.Run = ProcessRunner.default_run) -> Path:
        """`<git common dir>/gated-dev/flow` of the repository at `root`."""
        out = str(run("git", ["-C", str(root), "rev-parse", "--git-common-dir"]).stdout).strip()
        if out == "":
            raise FlowError(f"{root}: git printed no common dir")
        common = Path(out)
        if not common.is_absolute():
            common = Path(root) / common
        return common / "gated-dev" / "flow"

    def __init__(
        self,
        *,
        directory: str | Path,
        parent: str,
        now: Clock = _default_now,
        is_alive: Callable[[int], bool] = _default_is_alive,
        max_runs: int = 1,
    ) -> None:
        self.directory = Path(directory)
        self.parent = parent
        self.now = now
        self.is_alive = is_alive
        self.max = max_runs
        self.started_at = self.iso(now())
        self.updated_at = self.started_at
        self.tickets: dict[str, dict] = {}
        self.picks: list[dict] = []
        self._locked_pid: int | None = None

    @property
    def path(self) -> Path:
        return self.directory / f"{self.parent}.json"

    @property
    def lock_path(self) -> Path:
        return self.directory / f"{self.parent}.lock"

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> bool:
        """Reads the file when there is one. Returns False for a new flow; raises on unreadable content."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False
        except (OSError, ValueError) as error:
            raise FlowError(f"cannot read {self.path}: {error}") from error
        if not isinstance(raw, dict) or raw.get("version") != self.VERSION or raw.get("parent") != self.parent:
            raise FlowError(f"{self.path} is not a version {self.VERSION} flow state of {self.parent}")
        tickets, picks = raw.get("tickets", {}), raw.get("picks", [])
        if not isinstance(tickets, dict) or not isinstance(picks, list) or not isinstance(raw.get("max", 1), int):
            raise FlowError(f"{self.path} has invalid tickets, picks or max")
        for key, ticket in tickets.items():
            if not isinstance(ticket, dict) or ticket.get("status") not in self.STATUSES:
                raise FlowError(f"{self.path}: ticket {key} has no valid status")
        self.started_at = raw.get("startedAt") or self.started_at
        self.updated_at = raw.get("updatedAt") or self.updated_at
        self.max = raw.get("max", 1)
        self.tickets = tickets
        self.picks = picks[-self.MAX_PICKS :]
        return True

    def to_dict(self) -> dict:
        return {
            "version": self.VERSION,
            "parent": self.parent,
            "startedAt": self.started_at,
            "updatedAt": self.updated_at,
            "max": self.max,
            "tickets": self.tickets,
            "picks": self.picks[-self.MAX_PICKS :],
        }

    def save(self) -> None:
        """Atomic write (temp file + rename); sets `updatedAt`."""
        self.updated_at = self.iso(self.now())
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as error:
            raise FlowError(f"cannot write {self.path}: {error}") from error

    # --- lock -----------------------------------------------------------------

    def acquire(self, pid: int | None = None) -> None:
        """Takes `<PARENT>.lock` (pid inside). A lock of a dead pid is replaced; a live one raises."""
        pid = pid if pid is not None else os.getpid()
        self.directory.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                holder = self._lock_holder()
                if holder is not None and self.is_alive(holder):
                    raise FlowError(f"{self.parent}: another /ticket-flow driver is running (pid {holder}, {self.lock_path})") from None
                self.lock_path.unlink(missing_ok=True)  # stale: the pid is gone or the file is garbage
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"{pid}\n")
            self._locked_pid = pid
            return
        raise FlowError(f"{self.parent}: cannot take the lock {self.lock_path}")

    def release(self) -> None:
        """Removes the lock when this object holds it."""
        if self._locked_pid is not None and self._lock_holder() == self._locked_pid:
            self.lock_path.unlink(missing_ok=True)
        self._locked_pid = None

    @contextmanager
    def transaction(self) -> Iterator[bool]:
        """Holds the lock while the caller loads, changes and saves; yields whether a file was loaded."""
        self.acquire()
        try:
            yield self.load()
        finally:
            self.release()

    def _lock_holder(self) -> int | None:
        try:
            return int(self.lock_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    # --- changes --------------------------------------------------------------

    def record_pick(self, *, key: str | None, reason: str) -> None:
        """Appends a decision (`key` None: nothing ready); only the last MAX_PICKS stay."""
        self.picks = [*self.picks, {"at": self.iso(self.now()), "key": key, "reason": reason}][-self.MAX_PICKS :]

    def add_launched(self, key: str, *, summary: str, reason: str, worktree: str | None = None) -> dict:
        ticket: dict[str, Any] = {
            "status": "launched",
            "summary": summary,
            "reason": reason,
            "launchedAt": self.iso(self.now()),
            "worktree": worktree,
            "stage": None,
            "prUrl": None,
            "relaunches": 0,
            "staleWarnedAt": None,
        }
        self.tickets[key] = ticket
        return ticket

    def skip(self, key: str, reason: str = "") -> None:
        """Marks a ticket skipped; a running one is only marked, its session is not touched."""
        self.tickets[key] = {**self.tickets.get(key, {}), "status": "skipped", "reason": reason, "at": self.iso(self.now())}

    def retry(self, key: str) -> bool:
        """Forgets a skipped or aborted ticket so it can be picked again. False for any other state."""
        if self.tickets.get(key, {}).get("status") not in ("skipped", "aborted"):
            return False
        del self.tickets[key]
        return True
