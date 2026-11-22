"""Contract: the PR watcher (port of watch-pr.test.mjs).

A fake `gh` on PATH answers the polls; the watcher runs with every sleep elapsing at once
(`Entrypoints.watch_pr(fast=True)`), the requested delays are recorded.
"""

import json
import os
import re
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gd_testkit.entrypoints import Entrypoints
from gd_testkit.envs import IsolatedEnv
from gd_testkit.fakebin import FakeBin

PR_URL = "https://github.com/o/r/pull/7"
T0 = "2026-10-22T08:00:00Z"
T1 = "2026-10-22T09:00:00Z"
T2 = "2026-10-22T10:00:00Z"
MARKER = "<!-- gated-dev -->"


class Fail:
    """A poll whose `gh pr view` fails."""

    def __init__(self, message="gh: boom"):
        self.message = message


def view(**extra):
    return {"state": "OPEN", "mergedAt": None, "createdAt": T0, "reviews": [], "comments": [], **extra}


def comment(created_at, **extra):
    return {"author": {"login": "alice"}, "body": "please change this", "createdAt": created_at, **extra}


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Scenario:
    def __init__(self, base: Path, state_extra: dict | None = None):
        self.base = base
        self.ticket_dir = base / "project" / "docs" / "tickets" / "PROJ-9"
        self.ticket_dir.mkdir(parents=True)
        self.state_path = self.ticket_dir / "state.json"
        self.initial = {
            "key": "PROJ-9",
            "stage": "done",
            "prUrl": PR_URL,
            "updatedAt": "2026-10-22T07:00:00Z",
            **(state_extra or {}),
        }
        self.state_path.write_text(json.dumps(self.initial, indent=2))
        self.fb = FakeBin(base / "fake")
        self.sleep_log = base / "sleeps.log"

    def gh(self, polls: list):
        """Script `gh`: a poll is a view dict (optional "inline" list and "write_state" dict), or Fail.

        A successful poll is two calls (`pr view`, then `api .../comments`); a failed one only the first.
        """
        script: list[dict] = []
        for poll in polls:
            if isinstance(poll, Fail):
                script.append({"status": 1, "stderr": poll.message})
                continue
            rest = {k: v for k, v in poll.items() if k not in ("inline", "write_state")}
            script.append({"stdout": json.dumps(rest)})
            api: dict = {"stdout": "\n".join(json.dumps(c) for c in poll.get("inline", []))}
            if "write_state" in poll:
                api["write"] = {str(self.state_path): json.dumps({**self.initial, **poll["write_state"]})}
            script.append(api)
        self.fb.add("gh", script=script, snapshot=[str(self.state_path)])

    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def view_calls(self) -> list[dict]:
        return [c for c in self.fb.calls("gh") if c["argv"][0] == "pr"]

    def snapshots(self) -> list[dict]:
        """state.json as each `gh pr view` saw it: after the heartbeat of the previous poll."""
        return [json.loads(c["files"][str(self.state_path)]) for c in self.view_calls()]

    def sleeps(self) -> list[int]:
        return [int(x) for x in self.sleep_log.read_text().split()] if self.sleep_log.exists() else []


def run_watcher(scenario: Scenario, *args: str):
    proc = subprocess.run(
        [*FakeBin.absolute(Entrypoints.watch_pr(fast=True)), *args],
        capture_output=True,
        text=True,
        env=IsolatedEnv.clean(Entrypoints.env(), {"PATH": str(scenario.fb.path), "GD_TEST_SLEEP_LOG": str(scenario.sleep_log)}),
        timeout=60,
        check=False,
    )
    return proc


def watch(scenario: Scenario, polls: list):
    """Run the watcher on `polls`; returns (exit status, the result line as a dict, stderr)."""
    scenario.gh(polls)
    proc = run_watcher(scenario, "--state", str(scenario.state_path))
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, proc.stdout
    return proc.returncode, json.loads(lines[0]), proc.stderr


def outcome(tmp_path, polls, state_extra=None):
    return watch(Scenario(tmp_path, state_extra), polls)[1]


def test_human_issue_comment_newer_than_pr_creation_is_feedback(tmp_path):
    res = outcome(tmp_path, [view(comments=[comment(T1)])])
    assert res["outcome"] == "feedback"
    assert res["prUrl"] == PR_URL
    assert res["newestAt"] == T1


def test_review_and_inline_comment_count_as_feedback(tmp_path):
    review = {"author": {"login": "bob"}, "body": "needs work", "state": "CHANGES_REQUESTED", "submittedAt": T1}
    assert outcome(tmp_path / "a", [view(reviews=[review])])["outcome"] == "feedback"
    b = outcome(tmp_path / "b", [view(inline=[{"login": "carol", "body": "nit", "createdAt": T2}])])
    assert b["outcome"] == "feedback"
    assert b["newestAt"] == T2


def test_cutoff_is_last_addressed_comment_else_pr_creation(tmp_path):
    with_cutoff = Scenario(tmp_path / "a", {"lastAddressedCommentAt": T1})
    _, res, _ = watch(with_cutoff, [view(comments=[comment(T1)]), view(state="MERGED")])
    assert res["outcome"] == "merged"
    assert with_cutoff.sleeps() == [60000]
    older = outcome(tmp_path / "b", [view(comments=[comment(T0)]), view(state="CLOSED")])
    assert older["outcome"] == "closed"


def test_cutoff_written_to_the_file_between_polls_is_honoured(tmp_path):
    s = Scenario(tmp_path, {"lastAddressedCommentAt": T2})
    # The first poll is covered by the cutoff; a gh call lowers it, and the next poll must read the new one.
    _, res, _ = watch(
        s,
        [view(comments=[comment(T1)], write_state={"lastAddressedCommentAt": T0}), view(comments=[comment(T1)])],
    )
    assert res["outcome"] == "feedback"
    assert len(s.sleeps()) == 1


def test_bots_pipeline_replies_empty_comments_and_reviews_never_exit(tmp_path):
    noise = view(
        comments=[
            comment(T1, author={"login": "github-actions[bot]"}),
            comment(T1, body=f"done {MARKER}"),
            comment(T1, body="   "),
        ],
        reviews=[
            {"author": {"login": "bob"}, "body": "", "state": "COMMENTED", "submittedAt": T1},
            {"author": {"login": "bob"}, "body": "", "state": "APPROVED", "submittedAt": T1},
        ],
        inline=[{"login": "x[bot]", "body": "lint", "createdAt": T1}],
    )
    s = Scenario(tmp_path)
    _, res, _ = watch(s, [noise, noise, view(state="MERGED")])
    assert res["outcome"] == "merged"
    assert len(s.sleeps()) == 2


def test_merged_and_closed_exit_with_their_outcome(tmp_path):
    assert outcome(tmp_path / "a", [view(state="MERGED")])["outcome"] == "merged"
    assert outcome(tmp_path / "b", [view(state="CLOSED")])["outcome"] == "closed"


def test_merged_wins_over_feedback(tmp_path):
    assert outcome(tmp_path, [view(state="MERGED", comments=[comment(T1)])])["outcome"] == "merged"


def test_five_consecutive_gh_failures_exit_with_error(tmp_path):
    s = Scenario(tmp_path)
    _, res, _ = watch(s, [Fail("gh: network down")])
    assert res["outcome"] == "error"
    assert re.search(r"network down", res["message"])
    assert len(s.view_calls()) == 5
    assert len(s.sleeps()) == 4


def test_four_failures_a_success_four_failures_do_not_exit(tmp_path):
    s = Scenario(tmp_path)
    polls = [*[Fail("boom")] * 4, view(), *[Fail("boom")] * 4, view(state="MERGED")]
    _, res, _ = watch(s, polls)
    assert res["outcome"] == "merged"
    assert len(s.view_calls()) == 10


def test_missing_or_invalid_state_counts_as_a_failed_poll(tmp_path):
    a = Scenario(tmp_path / "a")
    a.state_path.write_text("{ not json")
    _, res, _ = watch(a, [view(state="MERGED")])
    assert res["outcome"] == "error"
    assert a.fb.calls("gh") == []

    b = Scenario(tmp_path / "b")
    b.state_path.write_text(json.dumps({"stage": "done"}))
    assert watch(b, [view(state="MERGED")])[1]["outcome"] == "error"

    c = Scenario(tmp_path / "c")
    c.state_path.unlink()
    assert watch(c, [view(state="MERGED")])[1]["outcome"] == "error"


def test_every_poll_writes_the_heartbeat_and_keeps_every_other_field(tmp_path):
    s = Scenario(tmp_path, {"prNumber": 7, "lastAddressedCommentAt": T0, "extra": {"a": 1}})
    watch(s, [view(), view(state="MERGED")])
    seen = s.snapshots()[1]
    assert isinstance(seen["watch"]["pid"], int)
    assert iso(seen["watch"]["startedAt"]) <= iso(seen["watch"]["heartbeatAt"])
    final = s.state()
    assert isinstance(final["watch"]["pid"], int)
    assert iso(final["watch"]["startedAt"]) <= iso(final["watch"]["heartbeatAt"])
    for key, value in s.initial.items():
        assert final[key] == value
    assert final["updatedAt"] == s.initial["updatedAt"]
    assert [p.name for p in s.ticket_dir.iterdir() if p.name.endswith(".tmp")] == []


def test_heartbeat_is_written_after_a_failed_poll_too(tmp_path):
    s = Scenario(tmp_path)
    watch(s, [Fail("x"), view(state="MERGED")])
    assert "heartbeatAt" in s.snapshots()[1]["watch"]
    assert "watch" not in s.snapshots()[0]


def test_started_at_stays_the_first_poll_time_while_heartbeat_advances(tmp_path):
    s = Scenario(tmp_path)
    watch(s, [view(), view(), view(state="MERGED")])
    first, second = s.snapshots()[1]["watch"], s.snapshots()[2]["watch"]
    final = s.state()["watch"]
    assert first["startedAt"] == second["startedAt"] == final["startedAt"]
    assert first["pid"] == second["pid"] == final["pid"]
    assert iso(first["heartbeatAt"]) < iso(second["heartbeatAt"]) < iso(final["heartbeatAt"])
    assert final["startedAt"] != final["heartbeatAt"]


def test_every_sleep_is_60000_ms_and_only_gh_is_run(tmp_path):
    s = Scenario(tmp_path)
    watch(s, [view(), view(), view(state="MERGED")])
    assert s.sleeps() == [60000, 60000]
    calls = s.fb.calls()
    assert calls
    assert {c["name"] for c in calls} == {"gh"}


def test_failed_heartbeat_write_is_logged_and_does_not_stop_the_watcher(tmp_path):
    s = Scenario(tmp_path)
    s.ticket_dir.chmod(0o555)  # no room for the temporary file
    try:
        assert not os.access(s.ticket_dir, os.W_OK), "cannot make the state dir read-only (running as root?)"
        _, res, stderr = watch(s, [view(state="MERGED")])
    finally:
        s.ticket_dir.chmod(stat.S_IRWXU)
    assert res["outcome"] == "merged"
    assert re.search(r"heartbeat", stderr)


@pytest.mark.parametrize(
    ("polls", "outcome_name", "code"),
    [
        ([view(comments=[comment(T1)])], "feedback", 0),
        ([view(state="MERGED")], "merged", 0),
        ([view(state="CLOSED")], "closed", 0),
        ([Fail("down")], "error", 1),
    ],
    ids=["feedback", "merged", "closed", "error"],
)
def test_main_prints_one_json_line_and_exits_per_outcome(tmp_path, polls, outcome_name, code):
    s = Scenario(tmp_path)
    s.gh(polls)
    before = datetime.now(UTC)
    proc = run_watcher(s, "--state", str(s.state_path))
    assert proc.returncode == code
    assert proc.stdout.endswith("\n")
    assert proc.stdout.count("\n") == 1
    parsed = json.loads(proc.stdout)
    assert parsed["outcome"] == outcome_name
    assert parsed["prUrl"] == PR_URL
    assert before - timedelta(seconds=1) <= iso(parsed["at"]) <= datetime.now(UTC) + timedelta(seconds=1)
    if outcome_name == "feedback":
        assert parsed["newestAt"] == T1
    if outcome_name == "error":
        assert parsed["message"]


@pytest.mark.parametrize(
    "argv",
    [[], ["--state"], ["--state", "docs/tickets/PROJ-9/state.json"], ["--bogus"]],
    ids=["none", "no-value", "relative", "unknown"],
)
def test_main_exits_2_with_a_usage_line_for_missing_or_relative_state(tmp_path, argv):
    s = Scenario(tmp_path)
    s.gh([view(state="MERGED")])
    proc = run_watcher(s, *argv)
    assert proc.returncode == 2
    lines = proc.stdout.splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["outcome"] == "usage"
    assert parsed["message"]
    assert s.fb.calls() == []


def test_pr_url_that_cannot_be_parsed_counts_as_a_failed_poll(tmp_path):
    s = Scenario(tmp_path, {"prUrl": "nope"})
    _, res, _ = watch(s, [view(state="MERGED")])
    assert res["outcome"] == "error"
    assert re.search(r"cannot parse", res["message"])
    assert s.fb.calls() == []
