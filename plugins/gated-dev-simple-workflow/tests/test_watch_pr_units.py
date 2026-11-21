"""Units of the PR watcher (gated_dev.watch_pr) with injected fakes."""

import json
from datetime import UTC, datetime, timedelta

from gated_dev import watch_pr as wp

PR_URL = "https://github.com/o/r/pull/7"
T0 = "2026-10-22T08:00:00Z"
T1 = "2026-10-22T09:00:00Z"
T2 = "2026-10-22T10:00:00Z"
CLOCK = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)


def test_constants():
    assert wp.POLL_MS == 60000
    assert wp.MAX_GH_FAILURES == 5
    assert wp.MARKER == "<!-- gated-dev -->"
    assert wp.EXIT == {"feedback": 0, "merged": 0, "closed": 0, "error": 1, "usage": 2}


def test_parse_pr_url_and_normalize_pr():
    assert wp.parse_pr_url(PR_URL) == {"owner": "o", "repo": "r", "number": 7}
    assert wp.parse_pr_url("not a url") is None
    assert wp.parse_pr_url(None) is None
    view = {
        "state": "OPEN",
        "mergedAt": None,
        "createdAt": T0,
        "reviews": [{"author": {"login": "b"}, "body": "x", "state": "COMMENTED", "createdAt": T1}],
        "comments": [],
    }
    pr = wp.normalize_pr(view, [{"login": "c", "body": "y", "createdAt": T2}])
    assert [f["login"] for f in pr["feedback"]] == ["b", "c"]
    assert pr["feedback"][0]["createdAt"] == T1


def test_newest_feedback_compares_instants_and_unparsable_cutoff_counts_everything():
    items = [
        {"login": "a", "body": "x", "createdAt": "2026-10-22T10:00:00+02:00"},  # 08:00Z, before T1
        {"login": "a", "body": "y", "createdAt": T2},
        {"login": "a", "body": "z", "createdAt": "garbage"},
    ]
    assert wp.newest_feedback_at(items, T1) == T2
    assert wp.newest_feedback_at(items[:1], T1) is None
    assert wp.newest_feedback_at(items[:1], "garbage") == "2026-10-22T10:00:00+02:00"
    assert wp.new_feedback_at({"createdAt": T1, "feedback": items}, None) == T2
    assert wp.new_feedback_at({"createdAt": T2, "feedback": items}, None) is None


def _state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"prUrl": PR_URL, "stage": "done"}))
    return path


def _merged_run(cmd, args, *, cwd=None):
    return json.dumps({"state": "MERGED", "createdAt": T0}) if args[0] == "pr" else ""


def test_failed_heartbeat_write_is_logged(tmp_path):
    path = _state(tmp_path)
    (tmp_path / "state.json.4242.tmp").mkdir()  # a directory where the temporary file would go
    logs: list[str] = []
    res = wp.watch(state_path=str(path), run=_merged_run, now=lambda: CLOCK, sleep=lambda ms: None, log=logs.append, pid=4242)
    assert res["outcome"] == "merged"
    assert any("heartbeat" in line for line in logs)


def test_heartbeat_and_clock_order(tmp_path):
    path = _state(tmp_path)
    ticks = iter(CLOCK + timedelta(minutes=i) for i in range(100))
    seen: list[dict] = []
    polls = iter([json.dumps({"state": "OPEN", "createdAt": T0}), json.dumps({"state": "MERGED", "createdAt": T0})])

    def run(cmd, args, *, cwd=None):
        assert cwd == str(tmp_path)
        if args[0] == "api":
            return ""
        seen.append(json.loads(path.read_text()).get("watch"))
        return next(polls)

    sleeps: list[int] = []
    res = wp.watch(state_path=str(path), run=run, now=lambda: next(ticks), sleep=sleeps.append, log=lambda _: None, pid=4242)
    assert res == {"outcome": "merged", "prUrl": PR_URL, "at": "2026-10-22T12:03:00.000Z"}
    assert sleeps == [60000]
    # started 12:00, first heartbeat 12:01, second poll sees it; final heartbeat 12:02, result 12:03
    assert seen[0] is None
    assert seen[1] == {"pid": 4242, "startedAt": "2026-10-22T12:00:00.000Z", "heartbeatAt": "2026-10-22T12:01:00.000Z"}
    final = json.loads(path.read_text())
    assert final["watch"] == {"pid": 4242, "startedAt": "2026-10-22T12:00:00.000Z", "heartbeatAt": "2026-10-22T12:02:00.000Z"}
    assert final["stage"] == "done"
    assert path.read_text().endswith("}\n")
