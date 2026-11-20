import pytest

from testkit import DG, GD
from testkit.porting import js_tests, read_map

PLUGIN_DIRS = [DG, GD]


def _ids(d):
    return d.name


@pytest.mark.parametrize("plugin_dir", PLUGIN_DIRS, ids=_ids)
def test_every_js_test_is_mapped(plugin_dir):
    mapped = {(f, n) for f, n, _ in read_map(plugin_dir / "tests" / "PORTING.md")}
    missing = sorted(set(js_tests(plugin_dir)) - mapped)
    assert not missing, f"{len(missing)} JS tests missing from PORTING.md, e.g. {missing[:5]}"


@pytest.mark.parametrize("plugin_dir", PLUGIN_DIRS, ids=_ids)
def test_no_stale_rows(plugin_dir):
    if not (plugin_dir / "test").is_dir():
        pytest.skip("JS tests are gone")
    existing = set(js_tests(plugin_dir))
    stale = sorted({(f, n) for f, n, _ in read_map(plugin_dir / "tests" / "PORTING.md")} - existing)
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


def test_js_tests_found():
    tests = js_tests(DG)
    assert len(tests) >= 200
    assert ("gate-hook.test.mjs", "node unavailable -> ask") in tests
