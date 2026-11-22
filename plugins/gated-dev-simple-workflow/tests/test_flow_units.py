"""Units of the flow core (gated_dev.flow): state, lock and observer, with injected fakes."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gated_dev.completed_run import CompletedRun
from gated_dev.errors import FlowError
from gated_dev.flow.observer import FlowObserver
from gated_dev.flow.state import FlowState
from gated_dev.launch.ticket_project import TicketProject

CLOCK = datetime(2026, 11, 22, 9, 0, 0, tzinfo=UTC)
PR = "https://github.com/o/r/pull/7"
CONFIG = {"ticketsDir": "docs/tickets"}


def new_state(tmp_path, *, is_alive=lambda pid: False, parent="PROJ-100") -> FlowState:
    return FlowState(directory=tmp_path / "flow", parent=parent, now=lambda: CLOCK, is_alive=is_alive)


# --- state --------------------------------------------------------------------


def test_round_trip(tmp_path):
    state = new_state(tmp_path)
    state.max = 3
    state.add_launched("PROJ-101", summary="Add export", reason="first", worktree="/wt")
    state.skip("PROJ-104", "needs a vendor contract")
    state.record_pick(key=None, reason="PROJ-103 blocked by PROJ-101")
    state.save()
    again = new_state(tmp_path)
    assert again.load() is True
    assert again.to_dict() == {**state.to_dict()}
    assert again.max == 3
    assert again.tickets["PROJ-101"]["status"] == "launched"
    assert again.tickets["PROJ-104"]["reason"] == "needs a vendor contract"
    assert again.picks == [{"at": "2026-11-22T09:00:00Z", "key": None, "reason": "PROJ-103 blocked by PROJ-101"}]


def test_new_flow_has_nothing_to_load(tmp_path):
    state = new_state(tmp_path)
    assert state.load() is False
    assert not state.exists()


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", json.dumps({"version": 2, "parent": "PROJ-100"}), json.dumps({"version": 1, "parent": "PROJ-9"}),
     json.dumps({"version": 1, "parent": "PROJ-100", "tickets": {"K-1": {"status": "weird"}}})],
)
def test_unreadable_state_raises(tmp_path, content):
    (tmp_path / "flow").mkdir()
    (tmp_path / "flow" / "PROJ-100.json").write_text(content)
    with pytest.raises(FlowError):
        new_state(tmp_path).load()


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    state = new_state(tmp_path)
    state.save()
    before = state.path.read_text()
    # A failing write (a directory where the temp file goes) keeps the old file intact.
    (state.directory / f"PROJ-100.json.{os.getpid()}.tmp").mkdir()
    state.add_launched("PROJ-101", summary="s", reason="r")
    with pytest.raises(FlowError, match="cannot write"):
        state.save()
    assert state.path.read_text() == before
    (state.directory / f"PROJ-100.json.{os.getpid()}.tmp").rmdir()
    state.save()
    assert sorted(p.name for p in state.directory.iterdir()) == ["PROJ-100.json"]


def test_picks_are_capped_at_50(tmp_path):
    state = new_state(tmp_path)
    for i in range(60):
        state.record_pick(key=f"PROJ-{i}", reason="r")
    assert len(state.picks) == 50
    assert state.picks[0]["key"] == "PROJ-10"
    state.save()
    state.picks = [{"at": "x", "key": None, "reason": str(i)} for i in range(70)]
    state.path.write_text(json.dumps(state.to_dict() | {"picks": state.picks}))
    loaded = new_state(tmp_path)
    loaded.load()
    assert len(loaded.picks) == 50
    assert loaded.picks[-1]["reason"] == "69"


def test_skip_and_retry(tmp_path):
    state = new_state(tmp_path)
    state.add_launched("PROJ-101", summary="s", reason="r")
    assert state.retry("PROJ-101") is False  # launched: not retryable
    state.skip("PROJ-101", "later")
    assert state.tickets["PROJ-101"]["status"] == "skipped"
    assert state.tickets["PROJ-101"]["summary"] == "s"
    assert state.retry("PROJ-101") is True
    assert "PROJ-101" not in state.tickets
    assert state.retry("PROJ-101") is False


def test_flow_dir_is_in_the_git_common_dir(tmp_path):
    calls = []

    def run(file, argv):
        calls.append((file, argv))
        return CompletedRun(".git\n", "")

    assert FlowState.flow_dir(root=tmp_path, run=run) == tmp_path / ".git" / "gated-dev" / "flow"
    assert calls == [("git", ["-C", str(tmp_path), "rev-parse", "--git-common-dir"])]
    assert FlowState.flow_dir(root=tmp_path, run=lambda f, a: CompletedRun("/abs/common\n", "")) == Path("/abs/common/gated-dev/flow")
    with pytest.raises(FlowError):
        FlowState.flow_dir(root=tmp_path, run=lambda f, a: CompletedRun("\n", ""))


# --- lock ---------------------------------------------------------------------


def test_lock_written_and_released(tmp_path):
    state = new_state(tmp_path)
    state.acquire(pid=4242)
    assert state.lock_path.read_text().strip() == "4242"
    state.release()
    assert not state.lock_path.exists()


def test_second_driver_is_refused_while_the_first_lives(tmp_path):
    first = new_state(tmp_path, is_alive=lambda pid: True)
    first.acquire(pid=111)
    second = new_state(tmp_path, is_alive=lambda pid: pid == 111)
    with pytest.raises(FlowError, match="another /ticket-flow driver is running \\(pid 111"):
        second.acquire(pid=222)
    second.release()  # not the holder: leaves the lock alone
    assert first.lock_path.read_text().strip() == "111"


def test_stale_lock_of_a_dead_pid_is_replaced(tmp_path):
    state = new_state(tmp_path, is_alive=lambda pid: False)
    state.directory.mkdir()
    state.lock_path.write_text("999\n")
    state.acquire(pid=222)
    assert state.lock_path.read_text().strip() == "222"


def test_garbage_lock_counts_as_stale(tmp_path):
    state = new_state(tmp_path, is_alive=lambda pid: True)
    state.directory.mkdir()
    state.lock_path.write_text("junk")
    state.acquire(pid=5)
    assert state.lock_path.read_text().strip() == "5"


def test_default_is_alive():
    assert FlowState._default_is_alive(os.getpid()) is True
    assert FlowState._default_is_alive(2**22 + 12345) is False


# --- observer -----------------------------------------------------------------


class Repo:
    """Fake git worktrees plus `state.json` files, and a fake `gh`."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.worktrees: dict[str, tuple[str, dict | None]] = {}  # key -> (branch suffix, state.json)
        self.prs: dict[str, str] = {}
        self.gh_calls: list[list[str]] = []
        self.gh_fail = False

    def add_run(self, key, stage="dev", *, extra=None, branch=None):
        wt = self.tmp / f"wt-{key}"
        (wt / "docs" / "tickets" / key).mkdir(parents=True, exist_ok=True)
        if stage is not None:
            (wt / "docs" / "tickets" / key / "state.json").write_text(json.dumps({"stage": stage, **(extra or {})}))
        self.worktrees[key] = (branch or f"{key}/work", None)
        return wt

    def git(self, file, argv):
        blocks = [f"worktree {self.tmp}\nbranch refs/heads/main"]
        blocks += [f"worktree {self.tmp / f'wt-{k}'}\nbranch refs/heads/{b}" for k, (b, _) in self.worktrees.items()]
        return CompletedRun("\n\n".join(blocks) + "\n", "")

    def gh(self, cmd, args, *, cwd=None):
        self.gh_calls.append(args)
        if self.gh_fail:
            raise RuntimeError("gh failed")
        return json.dumps({"state": self.prs[args[2]]})

    def observer(self):
        return FlowObserver(TicketProject(self.tmp, self.git), run=self.gh)


def launched(state, key, **fields):
    ticket = state.add_launched(key, summary="s", reason="r", worktree=fields.pop("worktree", None))
    ticket.update(fields)
    return ticket


@pytest.mark.parametrize(
    ("stage", "slot"),
    [
        (None, True),
        ("spec", True),
        ("plan", True),
        ("awaiting_plan_approval", True),
        ("dev", True),
        ("review", True),
        ("complete", True),
        ("addressing_review", True),
        ("done", False),
    ],
)
def test_every_stage_is_observed_and_slots_follow_d6(tmp_path, stage, slot):
    repo = Repo(tmp_path)
    wt = repo.add_run("PROJ-1", stage, extra={"prUrl": PR, "watch": {"heartbeatAt": "2026-11-22T08:59:00.000Z"}})
    repo.prs[PR] = "OPEN"
    state = new_state(tmp_path)
    launched(state, "PROJ-1")
    report = repo.observer().observe(state, config=CONFIG)
    obs = report["observations"]["PROJ-1"]
    assert (obs["status"], obs["stage"], obs["slot"]) == ("launched", stage, slot)
    assert obs["prUrl"] == (PR if stage else None)
    assert obs["heartbeatAt"] == ("2026-11-22T08:59:00.000Z" if stage else None)
    assert (obs["changedAt"] is not None) is (stage is not None)
    assert obs["changed"] is (stage is not None)
    assert state.tickets["PROJ-1"]["worktree"] == str(wt)
    assert state.tickets["PROJ-1"]["stage"] == stage
    assert state.tickets["PROJ-1"]["prUrl"] == (PR if stage else None)
    assert report["slotsUsed"] == (1 if slot else 0)
    assert report["freeSlots"] == (0 if slot else 1)


def test_run_without_state_json_is_a_just_launched_slot(tmp_path):
    repo = Repo(tmp_path)
    repo.add_run("PROJ-1", None)
    state = new_state(tmp_path)
    launched(state, "PROJ-1")
    report = repo.observer().observe(state, config=CONFIG)
    assert report["observations"]["PROJ-1"]["slot"] is True
    assert report["observations"]["PROJ-1"]["changedAt"] is None


def test_stage_merged_marks_merged(tmp_path):
    repo = Repo(tmp_path)
    repo.add_run("PROJ-1", "merged", extra={"prUrl": PR})
    state = new_state(tmp_path)
    launched(state, "PROJ-1")
    repo.observer().observe(state, config=CONFIG)
    assert state.tickets["PROJ-1"]["status"] == "merged"
    assert repo.gh_calls == []


def test_merged_via_gh_while_the_run_is_still_done(tmp_path):
    repo = Repo(tmp_path)
    repo.add_run("PROJ-1", "done", extra={"prUrl": PR})
    repo.prs[PR] = "MERGED"
    state = new_state(tmp_path)
    launched(state, "PROJ-1")
    report = repo.observer().observe(state, config=CONFIG)
    assert state.tickets["PROJ-1"]["status"] == "merged"
    assert report["observations"]["PROJ-1"]["status"] == "merged"
    assert repo.gh_calls == [["pr", "view", PR, "--json", "state"]]


def test_open_pr_stays_launched_and_gh_is_not_asked_in_dev(tmp_path):
    repo = Repo(tmp_path)
    repo.add_run("PROJ-1", "done", extra={"prUrl": PR})
    repo.add_run("PROJ-2", "dev", extra={"prUrl": PR})
    repo.prs[PR] = "OPEN"
    state = new_state(tmp_path)
    launched(state, "PROJ-1")
    launched(state, "PROJ-2")
    repo.observer().observe(state, config=CONFIG)
    assert state.tickets["PROJ-1"]["status"] == "launched"
    assert len(repo.gh_calls) == 1


def test_gh_failure_is_reported_and_changes_nothing(tmp_path):
    repo = Repo(tmp_path)
    repo.add_run("PROJ-1", "done", extra={"prUrl": PR})
    repo.gh_fail = True
    state = new_state(tmp_path)
    launched(state, "PROJ-1")
    report = repo.observer().observe(state, config=CONFIG)
    assert state.tickets["PROJ-1"]["status"] == "launched"
    assert report["errors"] == ["PROJ-1: gh failed"]


def test_run_gone_after_a_worktree_is_aborted(tmp_path):
    repo = Repo(tmp_path)
    state = new_state(tmp_path)
    launched(state, "PROJ-1", worktree="/wt/PROJ-1", stage="dev")
    report = repo.observer().observe(state, config=CONFIG)
    assert state.tickets["PROJ-1"]["status"] == "aborted"
    assert report["observations"]["PROJ-1"]["slot"] is False
    assert report["freeSlots"] == 1


def test_aborted_stage_is_aborted(tmp_path):
    repo = Repo(tmp_path)
    repo.add_run("PROJ-1", "aborted")
    state = new_state(tmp_path)
    launched(state, "PROJ-1", worktree=str(tmp_path / "wt-PROJ-1"), stage="dev")
    repo.observer().observe(state, config=CONFIG)
    assert state.tickets["PROJ-1"]["status"] == "aborted"


def test_run_not_there_yet_is_not_aborted(tmp_path):
    repo = Repo(tmp_path)
    state = new_state(tmp_path)
    launched(state, "PROJ-1")  # no worktree, no stage: the session is starting
    repo.observer().observe(state, config=CONFIG)
    assert state.tickets["PROJ-1"]["status"] == "launched"


def test_run_gone_with_a_merged_pr_is_merged_not_aborted(tmp_path):
    repo = Repo(tmp_path)
    repo.prs[PR] = "MERGED"
    state = new_state(tmp_path)
    launched(state, "PROJ-1", worktree="/wt/x", stage="done", prUrl=PR)
    repo.observer().observe(state, config=CONFIG)
    assert state.tickets["PROJ-1"]["status"] == "merged"


def test_run_gone_with_an_open_pr_is_aborted(tmp_path):
    repo = Repo(tmp_path)
    repo.prs[PR] = "CLOSED"
    state = new_state(tmp_path)
    launched(state, "PROJ-1", worktree="/wt/x", stage="done", prUrl=PR)
    repo.observer().observe(state, config=CONFIG)
    assert state.tickets["PROJ-1"]["status"] == "aborted"


def test_several_runs_are_reported_and_leave_the_ticket_alone(tmp_path):
    repo = Repo(tmp_path)
    repo.add_run("PROJ-1", "dev")
    repo.worktrees["PROJ-1b"] = ("PROJ-1/other", None)
    state = new_state(tmp_path)
    launched(state, "PROJ-1")
    report = repo.observer().observe(state, config=CONFIG)
    assert state.tickets["PROJ-1"]["status"] == "launched"
    assert "several runs" in report["errors"][0]


def test_only_launched_tickets_are_observed(tmp_path):
    repo = Repo(tmp_path)
    repo.add_run("PROJ-2", "dev")
    state = new_state(tmp_path)
    state.skip("PROJ-2", "no")
    state.tickets["PROJ-3"] = {"status": "merged"}
    report = repo.observer().observe(state, config=CONFIG)
    assert report["observations"] == {}
    assert state.tickets["PROJ-2"]["status"] == "skipped"
    assert report["slotsUsed"] == 0


def test_slot_count_per_d6(tmp_path):
    repo = Repo(tmp_path)
    for key, stage in [("PROJ-1", "awaiting_plan_approval"), ("PROJ-2", "done"), ("PROJ-3", "addressing_review"), ("PROJ-4", None)]:
        repo.add_run(key, stage, extra={"prUrl": PR})
    repo.prs[PR] = "OPEN"
    state = new_state(tmp_path)
    state.max = 4
    for key in ("PROJ-1", "PROJ-2", "PROJ-3", "PROJ-4"):
        launched(state, key)
    state.skip("PROJ-5", "x")
    state.tickets["PROJ-6"] = {"status": "merged", "stage": "dev"}
    report = repo.observer().observe(state, config=CONFIG)
    assert report["slotsUsed"] == 3  # approval wait, review round, just launched; `done` is free
    assert report["freeSlots"] == 1
    state.max = 2
    assert FlowObserver.free_slots(state) == 0  # never negative


def test_runs_this_flow_did_not_launch_are_listed_not_picked(tmp_path):
    repo = Repo(tmp_path)
    repo.add_run("PROJ-7", "dev")
    repo.add_run("PROJ-8", "aborted")  # aborted runs do not count
    state = new_state(tmp_path)
    launched(state, "PROJ-1", worktree="/gone", stage="dev")
    report = repo.observer().observe(state, config=CONFIG, candidates=["PROJ-1", "PROJ-7", "PROJ-8", "PROJ-9"])
    assert report["foreign"] == ["PROJ-7"]
    assert report["slotsUsed"] == 0  # PROJ-1 is gone; foreign runs hold no flow slot
