"""hooks/gate.sh interpreter lookup (D1a/D1b): GATE_INFRA_PYTHON, python3.14, python3, always -I, fail closed."""

import os
import shutil
import subprocess

import pytest

from testkit import DG
from testkit.envs import IsolatedEnv
from testkit.fakebin import FakeBin
from testkit.hook import HookRunner
from testkit.pythons import Pythons

GATE_SH = DG / "hooks" / "gate.sh"
UNAVAILABLE = HookRunner.ASK_TEMPLATE.format("unparsable: python unavailable")
ENGINE_FAILED = HookRunner.ASK_TEMPLATE.format("gate-config: engine failed")
PUSH_FORCE = HookRunner.ASK_TEMPLATE.format("git-push-force: gated invocation")


def _bin(tmp_path) -> FakeBin:
    """A private PATH with only the tools gate.sh itself needs."""
    fake = FakeBin(tmp_path)
    for tool in ("dirname", "tr", "mktemp", "rm", "touch"):
        fake.link(tool)
    return fake


def _wrapper(fake: FakeBin, name: str, python: str, marker=None):
    body = f'touch "{marker}"\n' if marker else ""
    path = fake.path / name
    path.write_text(f'#!/bin/sh\n{body}exec "{python}" "$@"\n')
    path.chmod(0o755)
    return path


def _run(fake: FakeBin, command="git push -f", cwd=None, **env):
    proc = subprocess.run(
        [shutil.which("bash"), str(GATE_SH)],
        input=HookRunner.bash_input(command, cwd or fake.path).encode(),
        capture_output=True,
        env=IsolatedEnv.clean({"PATH": str(fake.path)}, env),
        cwd=cwd,
        check=False,
    )
    assert proc.returncode == 0
    return proc.stdout.decode()


def test_old_python3_asks_python_unavailable(tmp_path, old_python):
    fake = _bin(tmp_path)
    _wrapper(fake, "python3", old_python)
    assert _run(fake) == UNAVAILABLE


def test_missing_explicit_interpreter_asks_without_falling_back(tmp_path):
    fake = _bin(tmp_path)
    _wrapper(fake, "python3", Pythons.require_new_python(os.environ))
    assert _run(fake, GATE_INFRA_PYTHON="/nope") == UNAVAILABLE


def test_no_python_on_path_asks(tmp_path):
    assert _run(_bin(tmp_path)) == UNAVAILABLE


def test_python314_preferred_over_python3(tmp_path, old_python):
    fake = _bin(tmp_path)
    new = Pythons.require_new_python(os.environ)
    ran = tmp_path / "ran-python3.14"
    other = tmp_path / "ran-python3"
    _wrapper(fake, "python3.14", new, marker=ran)
    _wrapper(fake, "python3", old_python, marker=other)
    assert _run(fake) == PUSH_FORCE
    assert ran.exists()
    assert not other.exists()


def test_python3_used_when_no_python314(tmp_path):
    fake = _bin(tmp_path)
    ran = tmp_path / "ran"
    _wrapper(fake, "python3", Pythons.require_new_python(os.environ), marker=ran)
    assert _run(fake) == PUSH_FORCE
    assert ran.exists()


def test_broken_python3_first_on_path_asks_engine_failed(tmp_path):
    fake = _bin(tmp_path)
    broken = fake.path / "python3"
    broken.write_text("#!/bin/sh\nexit 1\n")
    broken.chmod(0o755)
    assert _run(fake) == ENGINE_FAILED


def test_explicit_interpreter_is_used_even_if_broken(tmp_path):
    fake = _bin(tmp_path)
    _wrapper(fake, "python3", Pythons.require_new_python(os.environ))
    broken = tmp_path / "broken"
    broken.write_text("#!/bin/sh\nexit 1\n")
    broken.chmod(0o755)
    assert _run(fake, GATE_INFRA_PYTHON=str(broken)) == ENGINE_FAILED


def test_planted_json_module_does_not_change_the_decision(tmp_path):
    fake = _bin(tmp_path)
    _wrapper(fake, "python3", Pythons.require_new_python(os.environ))
    planted = tmp_path / "planted"
    planted.mkdir()
    (planted / "json.py").write_text("raise SystemExit(0)\n")
    assert _run(fake, cwd=planted) == PUSH_FORCE
    assert _run(fake, cwd=planted, PYTHONPATH=str(planted)) == PUSH_FORCE


@pytest.mark.parametrize("value", ["0", "false", "OFF", "no"])
def test_gate_disabled_starts_no_interpreter(tmp_path, value):
    fake = _bin(tmp_path)
    ran = tmp_path / "ran"
    _wrapper(fake, "python3", Pythons.require_new_python(os.environ), marker=ran)
    assert _run(fake, GATE_ENABLED=value) == ""
    assert not ran.exists()
