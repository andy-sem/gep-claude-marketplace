import pytest

from testkit import REPO
from testkit.bridge import BridgeError, bridge, bridge_many, call, js_regexp


def test_calls_function():
    assert bridge("gated-dev:launch", "slugify", "Fix: Login page!") == "fix-login-page"


def test_reads_constant():
    assert bridge("gated-dev:watch-pr", "MARKER") == "<!-- gated-dev -->"


def test_regexp_is_encoded():
    assert js_regexp({"$regexp": "^a.c$", "flags": "i"}).search("ABC")


def test_js_error_becomes_bridge_error():
    with pytest.raises(BridgeError) as e:
        bridge("gated-dev:launch", "buildShellCommand")
    assert e.value.name == "TypeError"


def test_unknown_export_fails():
    with pytest.raises(BridgeError):
        bridge("gated-dev:launch", "noSuchExport")


def test_unqualified_module_is_rejected():
    with pytest.raises(BridgeError, match="only gated-dev"):
        bridge("config", "DEFAULT_CHECKS")


def test_async_function_is_awaited():
    root = bridge("gated-dev:launch", "findRoot", {"cwd": str(REPO)})
    assert isinstance(root, str)
    assert root


def test_error_shape_needs_exit_1():
    from testkit.bridge import _decode

    shaped = '{"$error": {"name": "X", "message": "m"}}'
    assert _decode(0, shaped, "", "m.e") == {"$error": {"name": "X", "message": "m"}}
    with pytest.raises(BridgeError) as e:
        _decode(1, shaped, "", "m.e")
    assert e.value.name == "X"
    with pytest.raises(RuntimeError, match="trace"):
        _decode(1, "oops", "trace", "m.e")


def test_missing_node_is_runtime_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RuntimeError):
        bridge("gated-dev:watch-pr", "POLL_MS")


def test_nested_call_args():
    assert bridge("gated-dev:launch", "shellQuote", call("gated-dev:launch", "slugify", "A B")) == "'a-b'"


def test_bridge_many_in_order():
    results = bridge_many([("gated-dev:launch", "slugify", ["A B"]), ("gated-dev:watch-pr", "POLL_MS", [])])
    assert results == ["a-b", 60000]


def test_bridge_many_raises_on_error():
    with pytest.raises(BridgeError) as e:
        bridge_many([("gated-dev:watch-pr", "POLL_MS", []), ("gated-dev:watch-pr", "nope", [])])
    assert "nope" in e.value.message


def test_bridge_gated_dev_module():
    assert bridge("gated-dev:launch", "slugify", "Fix: Login page!") == "fix-login-page"
    assert bridge("gated-dev:watch-pr", "POLL_MS") == 60000
