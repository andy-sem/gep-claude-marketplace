import json
import sys
import time
import urllib.error
import urllib.request

import pytest

from testkit.envs import clean_env
from testkit.jev_mock import JevMock, probs
from testkit.projects import provision_project, temp_project
from testkit.pythons import find_old_python


def _post(url: str, body: dict, timeout: float = 5) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_clean_env_drops_gate_vars(monkeypatch):
    monkeypatch.setenv("GATE_CHECKS", "nope")
    monkeypatch.setenv("TYPESAFE_API_KEY", "x")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/x")
    env = clean_env()
    assert "GATE_CHECKS" not in env
    assert "TYPESAFE_API_KEY" not in env
    assert "CLAUDE_PROJECT_DIR" not in env
    assert "PATH" in env
    env = clean_env({"GATE_CHECKS": "a", "X": "1"}, {"GATE_CHECKS": "b"})
    assert env["GATE_CHECKS"] == "b"
    assert env["X"] == "1"


def test_jev_mock_records_and_answers():
    with JevMock() as jev:
        jev.answer(probs(0.1, 0.2, 0.3, 0.4), question="destructive")
        status, raw = _post(jev.url, {"state": {"command": "ls"}})
        assert status == 200
        body = json.loads(raw)
        assert body["answers"]["destructive"] == {
            "type": "choice",
            "probabilities": {"unrelated": 0.1, "read_only": 0.2, "cloud_or_data_change": 0.3, "destructive": 0.4},
        }
        assert body["usage"] == {"input_tokens": 1000, "output_tokens": 10}
        assert jev.hits == 1
        assert jev.bodies == [{"state": {"command": "ls"}}]


def test_jev_mock_status_and_malformed():
    with JevMock() as jev:
        jev.answer(kind="status", status=429)
        assert _post(jev.url, {})[0] == 429
        assert jev.hits == 1
        jev.answer(kind="malformed")
        assert jev.hits == 0
        assert _post(jev.url, {}) == (200, b"{")
        assert jev.hits == 1


def test_jev_mock_hang_released_on_exit():
    start = None
    with JevMock() as jev:
        jev.answer(kind="hang")
        with pytest.raises((TimeoutError, urllib.error.URLError)):
            _post(jev.url, {}, timeout=0.2)
        start = time.monotonic()
    assert time.monotonic() - start < 2


def test_temp_project_has_git_root(tmp_path):
    root = temp_project(tmp_path, {"a/b.sh": "echo hi\n"})
    assert (root / ".git").is_dir()
    assert (root / "a/b.sh").read_text() == "echo hi\n"
    assert root == root.resolve()
    prov = provision_project(tmp_path)
    assert (prov / "scripts/provision-cloud-app-dev.mjs").is_file()
    assert "cloudctl" in (prov / "scripts/deploy-cloud-app-dev.mjs").read_text()


def test_jev_mock_status_kind_needs_status():
    with JevMock() as jev, pytest.raises(ValueError, match="status"):
        jev.answer(kind="status")


def test_old_python_env_must_really_be_old(monkeypatch, tmp_path):
    monkeypatch.setenv("OLD_PYTHON", sys.executable)
    with pytest.raises(RuntimeError, match="OLD_PYTHON"):
        find_old_python()
    monkeypatch.setenv("OLD_PYTHON", str(tmp_path / "no-such-python"))
    with pytest.raises(RuntimeError, match="OLD_PYTHON"):
        find_old_python()


def test_old_python_env_accepted_when_old(monkeypatch):
    monkeypatch.delenv("OLD_PYTHON", raising=False)
    old = find_old_python()
    if old is None:
        pytest.skip("no Python < 3.14 available")
    monkeypatch.setenv("OLD_PYTHON", old)
    assert find_old_python() == old


def test_jev_mock_records_headers():
    with JevMock() as jev:
        req = urllib.request.Request(jev.url, data=b"{}", headers={"X-Probe": "abc"})
        urllib.request.urlopen(req, timeout=5).read()
        assert len(jev.headers) == 1
        assert jev.headers[0]["x-probe"] == "abc"
        jev.answer()
        assert jev.headers == []


def test_jev_mock_retry_after_and_raw():
    with JevMock() as jev:
        req = urllib.request.Request(jev.url, data=b"{}")
        jev.answer(kind="status", status=429, retry_after="0")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code == 429
        assert e.value.headers["retry-after"] == "0"
        jev.answer(kind="raw", body={"answers": {}})
        status, raw = _post(jev.url, {})
        assert status == 200
        assert json.loads(raw) == {"answers": {}}


def test_jev_mock_sequence_repeats_last():
    with JevMock() as jev:
        jev.sequence({"kind": "status", "status": 429}, {"probs": probs(0, 0, 0, 1)})
        codes = [_post(jev.url, {})[0] for _ in range(3)]
        assert codes == [429, 200, 200]
        assert jev.hits == 3
        jev.sequence({"kind": "malformed"})
        assert jev.hits == 0
