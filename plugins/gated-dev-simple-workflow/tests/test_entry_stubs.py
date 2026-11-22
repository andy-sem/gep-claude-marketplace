import json
import os
import subprocess

import pytest

from gd_testkit import GD
from gd_testkit.envs import IsolatedEnv
from gd_testkit.pythons import Pythons
from gd_testkit.stubs import EntryStubs

STUBS = EntryStubs.stubs_of(GD)


@pytest.mark.parametrize("stub", STUBS, ids=EntryStubs.stub_id)
def test_stub_parses_as_python_37(stub):
    EntryStubs.check_parses_as_37(stub[0])


@pytest.mark.parametrize("stub", STUBS, ids=EntryStubs.stub_id)
def test_old_python_gets_exit_3(old_python, stub):
    EntryStubs.check_old_python_exit_3(old_python, stub[0])


def test_314_notify_stub_hands_over_to_the_real_package(tmp_path):
    # P10: not the planted module next to the cwd; GATED_DEV_NOTIFY=0 makes the hook exit 0 at once.
    (tmp_path / "gated_dev.py").write_text("raise SystemExit(99)\n")
    proc = subprocess.run(
        [Pythons.require_new_python(os.environ), "-I", str(GD / "hooks" / "notify.py")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=IsolatedEnv.clean({"GATED_DEV_NOTIFY": "0"}),
        check=False,
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_314_watch_pr_stub_hands_over_to_the_real_package(tmp_path):
    # P11: not the planted module next to the cwd; a bad argument gets the usage line without any gh call.
    (tmp_path / "gated_dev.py").write_text("raise SystemExit(99)\n")
    proc = subprocess.run(
        [Pythons.require_new_python(os.environ), "-I", str(GD / "scripts" / "watch_pr.py"), "--bogus"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=IsolatedEnv.clean(),
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
    assert json.loads(proc.stdout)["outcome"] == "usage"


def test_314_launch_stub_hands_over_to_the_real_package(tmp_path):
    # P12: not the planted module next to the cwd; --help prints the usage without any git or orca call.
    (tmp_path / "gated_dev.py").write_text("raise SystemExit(99)\n")
    proc = subprocess.run(
        [Pythons.require_new_python(os.environ), "-I", str(GD / "scripts" / "launch.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=IsolatedEnv.clean(),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("Usage: launch.py ")


def test_314_flow_stub_hands_over_to_the_real_package(tmp_path):
    # P13: not the planted module next to the cwd; --help prints the usage without any git or gh call.
    (tmp_path / "gated_dev.py").write_text("raise SystemExit(99)\n")
    proc = subprocess.run(
        [Pythons.require_new_python(os.environ), "-I", str(GD / "scripts" / "flow.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=IsolatedEnv.clean(),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("Usage: flow.py ")
