import pytest

from testkit.bridge import BridgeError, bridge


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
