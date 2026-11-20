import pytest

from testkit.bridge import BridgeError, bridge, bridge_many, call, js_regexp


def test_calls_function(tmp_path):
    assert bridge("paths", "projectDir", {"CLAUDE_PROJECT_DIR": str(tmp_path)}, "/") == str(tmp_path.resolve())


def test_reads_constant():
    assert bridge("config", "DEFAULT_CHECKS") == ["destructive"]


def test_regexp_is_encoded():
    assert bridge("gate-scripts", "globToRegExp", "*.sh") == {"$regexp": "^[^/]*\\.sh$", "flags": ""}


def test_js_error_becomes_bridge_error():
    with pytest.raises(BridgeError) as e:
        bridge("config", "readConfig", {"GATE_CHECKS": "nope"})
    assert e.value.name == "ConfigError"
    assert 'unknown pack "nope"' in e.value.message


def test_unknown_export_fails():
    with pytest.raises(BridgeError):
        bridge("paths", "noSuchExport")


def test_async_function_is_awaited(tmp_path):
    result = bridge("check", "effectiveConfig", {"CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert isinstance(result, dict)
    assert result != {}


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
        bridge("config", "DEFAULT_CHECKS")


def test_nested_call_args():
    result = bridge("gate-engine", "composeRules", [call("gate-engine", "packPath", "destructive")])
    assert isinstance(result["rules"], list)
    assert result["rules"]


def test_bridge_many_in_order():
    path = bridge("gate-engine", "packPath", "base")
    results = bridge_many([("gate-engine", "packPath", ["base"]), ("config", "DEFAULT_CHECKS", [])])
    assert results == [path, ["destructive"]]


def test_bridge_many_raises_on_error():
    with pytest.raises(BridgeError) as e:
        bridge_many([("config", "DEFAULT_CHECKS", []), ("gate-engine", "loadRules", ["/nope.json"])])
    assert e.value.name == "RulesError"


def test_js_regexp():
    assert js_regexp(bridge("gate-scripts", "globToRegExp", "a/*.js")).search("a/b.js")


def test_bridge_gated_dev_module():
    assert bridge("gated-dev:launch", "slugify", "Fix: Login page!") == "fix-login-page"
    assert bridge("gated-dev:watch-pr", "POLL_MS") == 60000
    assert bridge("paths", "projectDir", {"CLAUDE_PROJECT_DIR": "/"}, "/")  # unqualified still means the gate lib
