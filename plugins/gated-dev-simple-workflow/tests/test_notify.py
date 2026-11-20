"""Contract: the Notification hook (port of notify.test.mjs)."""

import json
import shutil
import subprocess

import pytest

from testkit import GD
from testkit.envs import clean_env
from testkit.fakebin import FakeBin, absolute

JQ = shutil.which("jq")
EVENT = json.dumps({"hook_event_name": "Notification", "message": "Claude needs your permission to use Bash"})
needs_jq = pytest.mark.skipif(JQ is None, reason="jq not installed")


def run_notify(impl, tmp_path, *, os_name="Darwin", env=None, stdin="", with_jq=True, notifiers=("osascript", "notify-send"), args=()):
    """Run the hook with a PATH that holds only stubs. Returns (status, stderr, call).

    `call` is [notifier, *its arguments] of the one notifier that ran, or None.
    """
    fb = FakeBin(tmp_path)
    fb.add("uname", stdout=f"{os_name}\n")
    fb.link("cat")
    for name in notifiers:
        fb.add(name)
    if with_jq and JQ:
        fb.link("jq")
    proc = subprocess.run(
        [*absolute(impl.notify()), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=clean_env(impl.env(), {"PATH": str(fb.path)}, env or {}),
        timeout=30,
        check=False,
    )
    calls = [c for c in fb.calls() if c["name"] in notifiers]
    assert len(calls) <= 1
    call = [calls[0]["name"], *calls[0]["argv"]] if calls else None
    return proc.returncode, proc.stderr, call


def test_hooks_json_registers_notification_hook(impl):
    cfg = json.loads((GD / "hooks" / "hooks.json").read_text())
    command = cfg["hooks"]["Notification"][0]["hooks"][0]["command"]
    if impl.name == "js":
        assert command == 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/notify.sh"'
    else:
        assert "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" in command
        assert "notify.py" in command


def test_silent_without_ticket_flow_key(impl, tmp_path):
    status, _, call = run_notify(impl, tmp_path, stdin=EVENT)
    assert status == 0
    assert call is None


def test_notify_off_switch(impl, tmp_path):
    status, _, call = run_notify(impl, tmp_path, stdin=EVENT, env={"TICKET_FLOW_KEY": "PROJ-1", "GATED_DEV_NOTIFY": "0"})
    assert status == 0
    assert call is None


@needs_jq
def test_macos_osascript_with_key_title_and_event_message(impl, tmp_path):
    status, _, call = run_notify(impl, tmp_path, stdin=EVENT, env={"TICKET_FLOW_KEY": "PROJ-1"})
    assert status == 0
    assert call[0] == "osascript"
    assert call[-2:] == ["PROJ-1 needs you", "Claude needs your permission to use Bash"]
    assert "--" in call


@needs_jq
def test_linux_notify_send_with_key_title_and_event_message(impl, tmp_path):
    status, _, call = run_notify(impl, tmp_path, os_name="Linux", stdin=EVENT, env={"TICKET_FLOW_KEY": "PROJ-1"})
    assert status == 0
    assert call == ["notify-send", "--", "PROJ-1 needs you", "Claude needs your permission to use Bash"]


def test_linux_without_notify_send_is_silent(impl, tmp_path):
    status, _, call = run_notify(impl, tmp_path, os_name="Linux", stdin=EVENT, env={"TICKET_FLOW_KEY": "PROJ-1"}, notifiers=())
    assert status == 0
    assert call is None


def test_other_os_is_silent(impl, tmp_path):
    status, _, call = run_notify(impl, tmp_path, os_name="FreeBSD", stdin=EVENT, env={"TICKET_FLOW_KEY": "PROJ-1"})
    assert status == 0
    assert call is None


@pytest.mark.parametrize(
    "opts",
    [{"with_jq": False, "stdin": EVENT}, {"stdin": "not json"}, {"stdin": ""}],
    ids=["no-jq", "bad-json", "empty"],
)
def test_default_message_without_jq_or_bad_input(impl, tmp_path, opts):
    status, _, call = run_notify(impl, tmp_path, os_name="Linux", env={"TICKET_FLOW_KEY": "PROJ-1"}, **opts)
    assert status == 0
    assert call[-1] == "Claude needs your attention"


def test_a_failing_notifier_does_not_fail_the_hook(impl, tmp_path):
    fb = FakeBin(tmp_path)
    fb.add("uname", stdout="Darwin\n")
    fb.add("osascript", stderr="boom\n", status=1)
    fb.link("cat")
    proc = subprocess.run(
        absolute(impl.notify()),
        input=EVENT,
        capture_output=True,
        text=True,
        env=clean_env(impl.env(), {"PATH": str(fb.path), "TICKET_FLOW_KEY": "PROJ-1"}),
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert len(fb.calls("osascript")) == 1


def test_direct_mode_title_and_message_from_arguments(impl, tmp_path):
    status, _, call = run_notify(impl, tmp_path / "a", os_name="Linux", args=["PROJ-1 merged", "PR #7 merged"])
    assert status == 0
    assert call == ["notify-send", "--", "PROJ-1 merged", "PR #7 merged"]
    _, _, off = run_notify(impl, tmp_path / "b", os_name="Linux", args=["PROJ-1 merged", "x"], env={"GATED_DEV_NOTIFY": "0"})
    assert off is None
