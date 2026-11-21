"""Observes the runs a flow launched (plan 5.3) and counts the slots they hold (D6)."""

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from gated_dev.errors import LaunchError
from gated_dev.flow.state import FlowState
from gated_dev.launch.ticket_project import TicketProject
from gated_dev.watch.pr_client import PrClient


class FlowObserver:
    """Reads runs (`find_run`, `state.json`) and PRs (`gh`), and updates the flow state in memory.

    The caller saves the state. Nothing outside the flow state is written.
    """

    SLOT_STAGES = frozenset(("spec", "plan", "awaiting_plan_approval", "dev", "review", "complete", "addressing_review"))
    """Stages that need the pipeline or a person's plan approval. `done` (PR in review) is not one."""
    PR_STAGES = frozenset(("done", "addressing_review"))
    """Stages where the PR may have been merged without the run knowing yet."""

    def __init__(
        self,
        project: TicketProject,
        run: Callable[..., str] = PrClient.default_run,
    ) -> None:
        self.project = project
        self.run = run

    @classmethod
    def holds_slot(cls, ticket: Mapping) -> bool:
        """A launched ticket whose run has no `state.json` yet or is in a SLOT_STAGES stage."""
        return ticket.get("status") == "launched" and (ticket.get("stage") is None or ticket["stage"] in cls.SLOT_STAGES)

    @classmethod
    def slots_used(cls, state: FlowState) -> int:
        return sum(1 for ticket in state.tickets.values() if cls.holds_slot(ticket))

    @classmethod
    def free_slots(cls, state: FlowState) -> int:
        return max(0, state.max - cls.slots_used(state))

    @staticmethod
    def _read_run_state(path: Path) -> tuple[dict, float | None]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return (raw if isinstance(raw, dict) else {}), path.stat().st_mtime
        except (OSError, ValueError):
            return {}, None

    def _pr_state(self, url: str, cwd: str) -> str | None:
        view = json.loads(self.run("gh", ["pr", "view", url, "--json", "state"], cwd=cwd))
        return view.get("state") if isinstance(view, dict) else None

    def observe(self, state: FlowState, *, config: Mapping, candidates: Iterable[str] = ()) -> dict:
        """Updates every `launched` ticket of the state from its run.

        Returns `{observations: {key: {...}}, foreign: [key], slotsUsed, freeSlots, errors: [str]}`.
        An observation has `status, stage, slot, prUrl, heartbeatAt, changedAt, changed (stage moved)`.
        `foreign` lists the `candidates` that have a run this flow did not launch (not in the state).
        A failed `find_run` or `gh` call is listed in `errors` and leaves that ticket as it was.
        """
        observations: dict[str, dict] = {}
        errors: list[str] = []
        for key, ticket in list(state.tickets.items()):
            if ticket["status"] != "launched":
                continue
            observations[key] = self._observe_ticket(state, key, ticket, config, errors)
        foreign = []
        for key in candidates:
            if key in state.tickets:
                continue
            try:
                if self.project.find_run(key=key, config=config) is not None:
                    foreign.append(key)
            except LaunchError as error:
                errors.append(str(error))
                foreign.append(key)  # several runs: still not ours to pick
        return {
            "observations": observations,
            "foreign": foreign,
            "slotsUsed": self.slots_used(state),
            "freeSlots": self.free_slots(state),
            "errors": errors,
        }

    def _observe_ticket(self, state: FlowState, key: str, ticket: dict, config: Mapping, errors: list[str]) -> dict:
        previous_stage = ticket.get("stage")
        seen: dict = {"heartbeatAt": None, "changedAt": None}
        try:
            run = self.project.find_run(key=key, config=config)
        except LaunchError as error:
            errors.append(str(error))
            return self._result(ticket, seen, previous_stage)
        if run is None:
            self._run_gone(ticket, errors)
            return self._result(ticket, seen, previous_stage)

        run_state, mtime = self._read_run_state(Path(run["path"]) / config["ticketsDir"] / key / "state.json")
        watch = run_state.get("watch")
        seen["heartbeatAt"] = watch.get("heartbeatAt") if isinstance(watch, dict) else None
        seen["changedAt"] = state.iso(datetime.fromtimestamp(mtime, UTC)) if mtime is not None else None
        ticket["worktree"] = run["path"]
        ticket["stage"] = run["stage"]
        pr_url = run_state.get("prUrl")
        ticket["prUrl"] = pr_url if isinstance(pr_url, str) and pr_url else ticket.get("prUrl")

        if run["stage"] == "merged":
            ticket["status"] = "merged"
        elif run["stage"] in self.PR_STAGES and ticket["prUrl"]:
            try:
                if self._pr_state(ticket["prUrl"], run["path"]) == "MERGED":
                    ticket["status"] = "merged"
            except (RuntimeError, ValueError) as error:
                errors.append(f"{key}: {error}")
        return self._result(ticket, seen, previous_stage)

    def _run_gone(self, ticket: dict, errors: list[str]) -> None:
        """No run: aborted (a stage `aborted`, or the worktree is gone), unless the PR got merged."""
        if ticket.get("worktree") is None and ticket.get("stage") is None:
            return  # just launched, the worktree does not exist yet
        if ticket.get("prUrl"):
            try:
                if self._pr_state(ticket["prUrl"], self.project.root) == "MERGED":
                    ticket["status"] = "merged"  # cleanup after the merge removed the worktree
                    return
            except (RuntimeError, ValueError) as error:
                errors.append(f"{ticket['prUrl']}: {error}")
                return
        ticket["status"] = "aborted"

    def _result(self, ticket: dict, seen: dict, previous_stage: str | None) -> dict:
        return {
            "status": ticket["status"],
            "stage": ticket.get("stage"),
            "slot": self.holds_slot(ticket),
            "prUrl": ticket.get("prUrl"),
            "heartbeatAt": seen["heartbeatAt"],
            "changedAt": seen["changedAt"],
            "changed": ticket.get("stage") != previous_stage,
        }
