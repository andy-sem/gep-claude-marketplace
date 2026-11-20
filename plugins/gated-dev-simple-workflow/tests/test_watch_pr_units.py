"""Units of the PR watcher through the JS bridge. # retarget to gated_dev in P11"""

from testkit.bridge import bridge

PR_URL = "https://github.com/o/r/pull/7"
T0 = "2026-10-22T08:00:00Z"
T1 = "2026-10-22T09:00:00Z"
T2 = "2026-10-22T10:00:00Z"
MOD = "gated-dev:watch-pr"


def test_constants():
    assert bridge(MOD, "POLL_MS") == 60000
    assert bridge(MOD, "MARKER") == "<!-- gated-dev -->"


def test_parse_pr_url_and_normalize_pr():
    assert bridge(MOD, "parsePrUrl", PR_URL) == {"owner": "o", "repo": "r", "number": 7}
    assert bridge(MOD, "parsePrUrl", "not a url") is None
    view = {
        "state": "OPEN",
        "mergedAt": None,
        "createdAt": T0,
        "reviews": [{"author": {"login": "b"}, "body": "x", "state": "COMMENTED", "createdAt": T1}],
        "comments": [],
    }
    pr = bridge(MOD, "normalizePr", view, [{"login": "c", "body": "y", "createdAt": T2}])
    assert [f["login"] for f in pr["feedback"]] == ["b", "c"]
    assert pr["feedback"][0]["createdAt"] == T1
