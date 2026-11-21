import pytest

from testkit import DG, GD
from testkit.porting import js_tests, read_map

PLUGIN_DIRS = [DG, GD]

# JS tests deleted before their plugin's JS: the row stays as the record of the Python twin.
REMOVED_JS_TESTS = {
    ("watch-pr.test.mjs", "the watcher command passes destructive-guard with its defaults"),  # P9: imported check.mjs
    ("notify.test.mjs", "hooks.json registers notify.sh for Notification"),
    ("notify.test.mjs", "silent without TICKET_FLOW_KEY"),
    ("notify.test.mjs", "GATED_DEV_NOTIFY=0 turns it off"),
    ("notify.test.mjs", "macOS: osascript with key title and the event message"),
    ("notify.test.mjs", "Linux: notify-send with key title and the event message"),
    ("notify.test.mjs", "Linux without notify-send: silent, exit 0"),
    ("notify.test.mjs", "other OS: silent, exit 0"),
    ("notify.test.mjs", "default message without jq or with bad input"),
    ("notify.test.mjs", "a failing notifier does not fail the hook"),
    ("notify.test.mjs", "direct mode: title and message from arguments, no TICKET_FLOW_KEY needed"),
}


def _ids(d):
    return d.name


@pytest.mark.parametrize("plugin_dir", PLUGIN_DIRS, ids=_ids)
def test_every_js_test_is_mapped(plugin_dir):
    mapped = {(f, n) for f, n, _ in read_map(plugin_dir / "tests" / "PORTING.md")}
    missing = sorted(set(js_tests(plugin_dir)) - mapped)
    assert not missing, f"{len(missing)} JS tests missing from PORTING.md, e.g. {missing[:5]}"


@pytest.mark.parametrize("plugin_dir", PLUGIN_DIRS, ids=_ids)
def test_no_stale_rows(plugin_dir):
    # a plugin whose JS tests are gone (P9, P13) keeps its rows as the record
    if not (plugin_dir / "test").is_dir():
        pytest.skip("JS tests are gone")
    existing = set(js_tests(plugin_dir))
    stale = sorted({(f, n) for f, n, _ in read_map(plugin_dir / "tests" / "PORTING.md")} - existing - REMOVED_JS_TESTS)
    assert not stale, f"stale rows in PORTING.md, e.g. {stale[:5]}"


@pytest.mark.parametrize("plugin_dir", PLUGIN_DIRS, ids=_ids)
def test_targets_exist(plugin_dir):
    problems = []
    for js_file, name, target in read_map(plugin_dir / "tests" / "PORTING.md"):
        if target == "todo" or target.startswith("dropped:"):
            continue
        for one in target.split(", "):
            rel, _, func = one.partition("::")
            path = plugin_dir / rel
            if not path.is_file() or f"def {func}(" not in path.read_text():
                problems.append(f"{js_file}: {name} -> {one}")
    assert not problems, problems[:10]


@pytest.mark.parametrize("plugin_dir", PLUGIN_DIRS, ids=_ids)
def test_no_todo_rows(plugin_dir):
    todo = [(f, n) for f, n, target in read_map(plugin_dir / "tests" / "PORTING.md") if target == "todo"]
    assert not todo, todo[:5]


def test_js_tests_found():
    # the JS tests of both plugins are gone (P9, P13); the PORTING.md files stay as the record.
    assert not (DG / "test").exists()
    assert not (GD / "test").exists()
    assert js_tests(GD) == []
