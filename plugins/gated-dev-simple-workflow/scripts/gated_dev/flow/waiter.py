"""Waits for something the /ticket-flow driver has to act on (plan 5.4)."""

import copy
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime

from gated_dev.errors import FlowError
from gated_dev.flow.observer import FlowObserver
from gated_dev.flow.state import FlowState


class FlowWaiter:
    """Polls the runs of one flow and returns one outcome (first match wins, in this order).

    `slot-free`, `lost-watch`, `merged-orphan`, `stale`, `error`. Every poll reloads the state and
    saves it (under its lock) when an observation changed it.
    """

    MAX_FAILURES = 5
    """Polls in a row with a failed `gh` or git call (or a lock held by another process) before `error`."""
    RELAUNCH_CAP = 3
    """Relaunches (`/ticket KEY --resume`) the driver is asked for per ticket, then it is reported and left."""

    @staticmethod
    def _default_sleep(seconds: float) -> None:
        time.sleep(seconds)

    @staticmethod
    def _default_log(line: str) -> None:
        sys.stderr.write(f"{line}\n")

    def __init__(
        self,
        observer: FlowObserver,
        *,
        sleep: Callable[[float], None] = _default_sleep,
        log: Callable[[str], None] = _default_log,
    ) -> None:
        self.observer = observer
        self.sleep = sleep
        self.log = log

    @staticmethod
    def _parse(stamp: object) -> datetime | None:
        try:
            return datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
        except ValueError:
            return None

    @classmethod
    def _age_seconds(cls, stamp: object, now: datetime) -> float | None:
        moment = cls._parse(stamp)
        return (now - moment).total_seconds() if moment is not None else None

    def wait(
        self,
        *,
        state: FlowState,
        config: Mapping,
        poll_seconds: float = 60,
        stale_hours: float = 3,
        lost_watch_minutes: float = 10,
    ) -> dict:
        """Returns `{outcome, parent, tickets: [...], at}` (`error` has `message` instead of tickets)."""
        failures = 0
        while True:
            try:
                state.acquire()
            except FlowError as error:
                failures += 1
                self.log(f"poll failed ({failures}/{self.MAX_FAILURES}): {error}")
                if failures >= self.MAX_FAILURES:
                    return self._done(state, "error", message=str(error))
                self.sleep(poll_seconds)
                continue
            try:
                state.load()
                before = copy.deepcopy(state.tickets)
                result = self._poll(state, config, stale_hours * 3600, lost_watch_minutes * 60)
                if state.tickets != before:
                    state.save()
            except FlowError as error:
                return self._done(state, "error", message=str(error))
            finally:
                state.release()
            failures = failures + 1 if result["failed"] else 0
            if result["failed"]:
                self.log(f"poll failed ({failures}/{self.MAX_FAILURES}): {result['failed']}")
            if result["outcome"]:
                return self._done(state, result["outcome"], tickets=result["tickets"])
            if failures >= self.MAX_FAILURES:
                return self._done(state, "error", message=result["failed"])
            self.sleep(poll_seconds)

    def _done(self, state: FlowState, outcome: str, **extra: object) -> dict:
        return {"outcome": outcome, "parent": state.parent, **extra, "at": state.iso(state.now())}

    def _poll(self, state: FlowState, config: Mapping, stale_seconds: float, lost_seconds: float) -> dict:
        now = state.now()
        previous = {key: (ticket["status"], FlowObserver.holds_slot(ticket)) for key, ticket in state.tickets.items()}
        report = self.observer.observe(state, config=config)
        observed = report["observations"]
        failed = "; ".join(report["errors"])

        freed = [
            {"key": key, "status": state.tickets[key]["status"], "stage": state.tickets[key].get("stage"), "prUrl": state.tickets[key].get("prUrl")}
            for key, (_, held) in previous.items()
            if held and not FlowObserver.holds_slot(state.tickets[key])
        ]
        for key, (status, _) in previous.items():
            ticket = state.tickets[key]
            if status == "launched" and ticket["status"] == "merged" and ticket.get("stage") != "merged":
                age = self._age_seconds(observed.get(key, {}).get("heartbeatAt"), now)
                ticket["orphan"] = age is None or age > lost_seconds  # the merged PR has no watch left to tell the session

        outcome, tickets = None, []
        if freed:
            outcome, tickets = "slot-free", freed
        if outcome is None:
            outcome, tickets = self._relaunches(state, observed, now, lost_seconds)
        if outcome is None:
            tickets = self._stale(state, observed, now, stale_seconds)
            outcome = "stale" if tickets else None
        return {"outcome": outcome, "tickets": tickets, "failed": failed}

    def _relaunch_entry(self, state: FlowState, key: str, now: datetime) -> dict:
        """Counts a relaunch the driver is asked for; past the cap the ticket is reported once and left."""
        ticket = state.tickets[key]
        ticket.pop("orphan", None)
        entry = {"key": key, "prUrl": ticket.get("prUrl"), "stage": ticket.get("stage")}
        if ticket["relaunches"] >= self.RELAUNCH_CAP:
            ticket["relaunchCapReported"] = True
            return {**entry, "capped": True, "relaunches": ticket["relaunches"]}
        ticket["relaunches"] += 1
        ticket["lastRelaunchAt"] = state.iso(now)
        return {**entry, "capped": False, "relaunches": ticket["relaunches"]}

    def _relaunches(self, state: FlowState, observed: Mapping, now: datetime, lost_seconds: float) -> tuple[str | None, list[dict]]:
        lost, orphans = [], []
        for key, ticket in state.tickets.items():
            if ticket.get("relaunchCapReported"):
                continue
            recent = self._age_seconds(ticket.get("lastRelaunchAt"), now)
            if recent is not None and recent <= lost_seconds:
                continue  # a relaunched session needs time to start its watch
            if ticket["status"] == "launched" and ticket.get("stage") == "done" and ticket.get("prUrl") and key in observed:
                seen = observed[key]
                age = self._age_seconds(seen["heartbeatAt"] or seen["changedAt"], now)
                if age is not None and age > lost_seconds:
                    lost.append(key)
            elif ticket["status"] == "merged" and ticket.get("orphan"):
                orphans.append(key)
        if lost:
            return "lost-watch", [self._relaunch_entry(state, key, now) for key in lost]
        if orphans:
            return "merged-orphan", [self._relaunch_entry(state, key, now) for key in orphans]
        return None, []

    def _stale(self, state: FlowState, observed: Mapping, now: datetime, stale_seconds: float) -> list[dict]:
        found = []
        for key, seen in observed.items():
            ticket = state.tickets[key]
            if not seen["slot"] or ticket.get("stage") == "awaiting_plan_approval" or ticket.get("staleWarnedAt"):
                continue
            age = self._age_seconds(seen["changedAt"] or ticket.get("launchedAt"), now)
            if age is not None and age > stale_seconds:
                ticket["staleWarnedAt"] = state.iso(now)
                found.append({"key": key, "stage": ticket.get("stage"), "idleHours": round(age / 3600, 1)})
        return found
