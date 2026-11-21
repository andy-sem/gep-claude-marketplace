"""hooks/run-python.sh: interpreter lookup (D1a), -I, best-effort exit 0."""

import os
import shutil
import subprocess

from testkit import GD
from testkit.envs import clean_env
from testkit.fakebin import FakeBin
from testkit.pythons import require_new_python

RUN_PYTHON = GD / "hooks" / "run-python.sh"


def _bin(tmp_path) -> FakeBin:
    fake = FakeBin(tmp_path)
    fake.link("touch")
    return fake


def _wrapper(fake: FakeBin, name: str, python: str, marker=None):
    body = f'touch "{marker}"\n' if marker else ""
    path = fake.path / name
    path.write_text(f'#!/bin/sh\n{body}exec "{python}" "$@"\n')
    path.chmod(0o755)
    return path


def _script(tmp_path, body="import sys\nprint('ran', sys.argv[1:])\n"):
    script = tmp_path / "script.py"
    script.write_text(body)
    return script


def _run(fake: FakeBin, script, *args, cwd=None, **env):
    return subprocess.run(
        [shutil.which("bash"), str(RUN_PYTHON), str(script), *args],
        capture_output=True,
        text=True,
        env=clean_env({"PATH": str(fake.path)}, env),
        cwd=cwd,
        check=False,
    )


def test_python314_preferred_over_python3(tmp_path, old_python):
    fake = _bin(tmp_path)
    ran, other = tmp_path / "ran-314", tmp_path / "ran-3"
    _wrapper(fake, "python3.14", require_new_python(os.environ), marker=ran)
    _wrapper(fake, "python3", old_python, marker=other)
    _run(fake, _script(tmp_path))
    assert ran.exists()
    assert not other.exists()


def test_python3_used_when_no_python314(tmp_path):
    fake = _bin(tmp_path)
    ran = tmp_path / "ran"
    _wrapper(fake, "python3", require_new_python(os.environ), marker=ran)
    _run(fake, _script(tmp_path))
    assert ran.exists()


def test_explicit_interpreter_wins_and_a_broken_one_is_silent(tmp_path):
    fake = _bin(tmp_path)
    ran = tmp_path / "ran"
    _wrapper(fake, "python3", require_new_python(os.environ), marker=ran)
    proc = _run(fake, _script(tmp_path), GATE_INFRA_PYTHON="/nope")
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    assert not ran.exists()


def test_no_python_is_silent(tmp_path):
    proc = _run(_bin(tmp_path), _script(tmp_path))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_old_python_exit_3_is_silent(tmp_path, old_python):
    fake = _bin(tmp_path)
    _wrapper(fake, "python3", old_python)
    proc = _run(fake, GD / "hooks" / "notify.py", GATE_INFRA_PYTHON="", TICKET_FLOW_KEY="PROJ-1")
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_arguments_are_passed_through(tmp_path):
    fake = _bin(tmp_path)
    out = tmp_path / "out.txt"
    script = _script(tmp_path, f"import sys\nopen({str(out)!r}, 'w').write('|'.join(sys.argv[1:]))\n")
    _run(fake, script, "a b", "c", GATE_INFRA_PYTHON=require_new_python(os.environ))
    assert out.read_text() == "a b|c"


def test_planted_json_module_is_ignored(tmp_path):
    fake = _bin(tmp_path)
    planted = tmp_path / "planted"
    planted.mkdir()
    (planted / "json.py").write_text("raise SystemExit(99)\n")
    out = tmp_path / "out.txt"
    script = _script(tmp_path, f"import json\nopen({str(out)!r}, 'w').write(json.dumps([1]))\n")
    python = require_new_python(os.environ)
    _run(fake, script, cwd=planted, GATE_INFRA_PYTHON=python, PYTHONPATH=str(planted))
    assert out.read_text() == "[1]"
