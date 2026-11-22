"""Contract: the Notification hook (port of notify.test.mjs)."""

import json
import shutil
import subprocess

import pytest

from gd_testkit import GD
from gd_testkit.entrypoints import Entrypoints
from gd_testkit.envs import IsolatedEnv
from gd_testkit.fakebin import FakeBin

EVENT = json.dumps({"hook_event_name": "Notification", "message": "Claude needs your permission to use Bash"})


def run_notify(tmp_path, *, os_name="Darwin", env=None, stdin="", notifiers=("osascript", "notify-send"), args=()):
    """Run the hook with a PATH that holds only stubs. Returns (status, stderr, call).

    `call` is [notifier, *its arguments] of the one notifier that ran, or None.
    """
    fb = FakeBin(tmp_path)
    fb.add("uname", stdout=f"{os_name}\n")
    fb.link("cat")
    for name in notifiers:
        fb.add(name)
    proc = subprocess.run(
        [*FakeBin.absolute(Entrypoints.notify()), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=IsolatedEnv.clean(Entrypoints.env(), {"PATH": str(fb.path)}, env or {}),
        timeout=30,
        check=False,
    )
    calls = [c for c in fb.calls() if c["name"] in notifiers]
    assert len(calls) <= 1
    call = [calls[0]["name"], *calls[0]["argv"]] if calls else None
    return proc.returncode, proc.stderr, call


def test_hooks_json_registers_notification_hook():
    cfg = json.loads((GD / "hooks" / "hooks.json").read_text())
    command = cfg["hooks"]["Notification"][0]["hooks"][0]["command"]
    assert command == 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/hooks/notify.py"'


def test_silent_without_ticket_flow_key(tmp_path):
    status, _, call = run_notify(tmp_path, stdin=EVENT)
    assert status == 0
    assert call is None


def test_notify_off_switch(tmp_path):
    status, _, call = run_notify(tmp_path, stdin=EVENT, env={"TICKET_FLOW_KEY": "PROJ-1", "GATED_DEV_NOTIFY": "0"})
    assert status == 0
    assert call is None


def test_macos_osascript_with_key_title_and_event_message(tmp_path):
    status, _, call = run_notify(tmp_path, stdin=EVENT, env={"TICKET_FLOW_KEY": "PROJ-1"})
    assert status == 0
    assert call[0] == "osascript"
    assert call[-2:] == ["PROJ-1 needs you", "Claude needs your permission to use Bash"]
    assert "--" in call


def test_linux_notify_send_with_key_title_and_event_message(tmp_path):
    status, _, call = run_notify(tmp_path, os_name="Linux", stdin=EVENT, env={"TICKET_FLOW_KEY": "PROJ-1"})
    assert status == 0
    assert call == ["notify-send", "--", "PROJ-1 needs you", "Claude needs your permission to use Bash"]


def test_linux_without_notify_send_is_silent(tmp_path):
    status, _, call = run_notify(tmp_path, os_name="Linux", stdin=EVENT, env={"TICKET_FLOW_KEY": "PROJ-1"}, notifiers=())
    assert status == 0
    assert call is None


def test_other_os_is_silent(tmp_path):
    status, _, call = run_notify(tmp_path, os_name="FreeBSD", stdin=EVENT, env={"TICKET_FLOW_KEY": "PROJ-1"})
    assert status == 0
    assert call is None


@pytest.mark.parametrize("stdin", ["not json", "", "[1]", '{"message": 5}'], ids=["bad-json", "empty", "not-an-object", "not-a-string"])
def test_default_message_on_bad_input(tmp_path, stdin):
    status, _, call = run_notify(tmp_path, os_name="Linux", env={"TICKET_FLOW_KEY": "PROJ-1"}, stdin=stdin)
    assert status == 0
    assert call[-1] == "Claude needs your attention"


def test_a_failing_notifier_does_not_fail_the_hook(tmp_path):
    fb = FakeBin(tmp_path)
    fb.add("uname", stdout="Darwin\n")
    fb.add("osascript", stderr="boom\n", status=1)
    fb.link("cat")
    proc = subprocess.run(
        FakeBin.absolute(Entrypoints.notify()),
        input=EVENT,
        capture_output=True,
        text=True,
        env=IsolatedEnv.clean(Entrypoints.env(), {"PATH": str(fb.path), "TICKET_FLOW_KEY": "PROJ-1"}),
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert len(fb.calls("osascript")) == 1


def test_direct_mode_title_and_message_from_arguments(tmp_path):
    status, _, call = run_notify(tmp_path / "a", os_name="Linux", args=["PROJ-1 merged", "PR #7 merged"])
    assert status == 0
    assert call == ["notify-send", "--", "PROJ-1 merged", "PR #7 merged"]
    _, _, off = run_notify(tmp_path / "b", os_name="Linux", args=["PROJ-1 merged", "x"], env={"GATED_DEV_NOTIFY": "0"})
    assert off is None


def test_title_fallback_and_non_utf8_stdin(tmp_path):
    _, _, call = run_notify(tmp_path / "a", os_name="Linux", stdin='{"title": "T"}', env={"TICKET_FLOW_KEY": "PROJ-1"})
    assert call[-1] == "T"
    fb = FakeBin(tmp_path / "b")
    fb.add("uname", stdout="Linux\n")
    fb.add("notify-send")
    proc = subprocess.run(
        FakeBin.absolute(Entrypoints.notify()),
        input=b"\xff\xfe",
        capture_output=True,
        env=IsolatedEnv.clean(Entrypoints.env(), {"PATH": str(fb.path), "TICKET_FLOW_KEY": "PROJ-1"}),
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
    assert fb.calls("notify-send")[0]["argv"][-1] == "Claude needs your attention"


def test_arguments_are_passed_as_argv_not_interpolated(tmp_path):
    title, message = 'a "q" $(touch x)', "line1\nline2 `id`"
    _, _, call = run_notify(tmp_path, args=[title, message])
    assert call[-2:] == [title, message]
    assert not any(part.startswith("-e") for part in call[-2:])


def test_no_python_is_silent(tmp_path):
    fb = FakeBin(tmp_path)
    fb.add("uname", stdout="Linux\n")
    fb.add("notify-send")
    proc = subprocess.run(
        [shutil.which("bash"), str(GD / "hooks" / "run-python.sh"), str(GD / "hooks" / "notify.py")],
        input=EVENT,
        capture_output=True,
        text=True,
        env=IsolatedEnv.clean({"PATH": str(fb.path), "TICKET_FLOW_KEY": "PROJ-1", "GATE_INFRA_PYTHON": "/nope"}),
        timeout=30,
        check=False,
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    assert fb.calls() == []
