import json
import os
import subprocess

import pytest

from testkit import GD
from testkit.envs import clean_env
from testkit.pythons import require_new_python
from testkit.stubs import (
    check_314_imports_package,
    check_old_python_exit_3,
    check_parses_as_37,
    stub_id,
    stubs_of,
)

STUBS = stubs_of(GD)


@pytest.mark.parametrize("stub", STUBS, ids=stub_id)
def test_stub_parses_as_python_37(stub):
    check_parses_as_37(stub[0])


@pytest.mark.parametrize("stub", STUBS, ids=stub_id)
def test_old_python_gets_exit_3(old_python, stub):
    check_old_python_exit_3(old_python, stub[0])


@pytest.mark.parametrize("stub", [s for s in STUBS if s[1] not in ("notify", "watch_pr", "launch")], ids=stub_id)
def test_314_imports_package(tmp_path, stub):
    check_314_imports_package(tmp_path, *stub)


def test_314_notify_stub_hands_over_to_the_real_package(tmp_path):
    # P10: not the planted module next to the cwd; GATED_DEV_NOTIFY=0 makes the hook exit 0 at once.
    (tmp_path / "gated_dev.py").write_text("raise SystemExit(99)\n")
    proc = subprocess.run(
        [require_new_python(os.environ), "-I", str(GD / "hooks" / "notify.py")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=clean_env({"GATED_DEV_NOTIFY": "0"}),
        check=False,
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_314_watch_pr_stub_hands_over_to_the_real_package(tmp_path):
    # P11: not the planted module next to the cwd; a bad argument gets the usage line without any gh call.
    (tmp_path / "gated_dev.py").write_text("raise SystemExit(99)\n")
    proc = subprocess.run(
        [require_new_python(os.environ), "-I", str(GD / "scripts" / "watch_pr.py"), "--bogus"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=clean_env(),
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
    assert json.loads(proc.stdout)["outcome"] == "usage"


def test_314_launch_stub_hands_over_to_the_real_package(tmp_path):
    # P12: not the planted module next to the cwd; --help prints the usage without any git or orca call.
    (tmp_path / "gated_dev.py").write_text("raise SystemExit(99)\n")
    proc = subprocess.run(
        [require_new_python(os.environ), "-I", str(GD / "scripts" / "launch.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=clean_env(),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("Usage: launch.py ")
