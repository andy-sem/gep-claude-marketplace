import os
import stat

import pytest

from testkit import DG
from testkit.impl import select_impl
from testkit.pythons import find_python

PLUGIN_NAMES = ["destructive-guard", "gated-dev-simple-workflow"]


def _fake(dir_path, name):
    p = dir_path / name
    p.write_text("#!/bin/sh\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def test_defaults():
    assert select_impl("destructive-guard", {}).name == "py"
    assert select_impl("gated-dev-simple-workflow", {}).name == "js"


def test_destructive_guard_rejects_js():
    with pytest.raises(ValueError, match="no JS implementation"):
        select_impl("destructive-guard", {"GD_IMPL": "js"})
    assert select_impl("gated-dev-simple-workflow", {"GD_IMPL": "js"}).name == "js"


def test_gd_impl_overrides():
    assert select_impl("destructive-guard", {"GD_IMPL": "py"}).name == "py"


def test_gd_impl_typo_raises():
    with pytest.raises(ValueError, match="GD_IMPL"):
        select_impl("destructive-guard", {"GD_IMPL": "pyhton"})


def test_unknown_plugin_raises():
    with pytest.raises(ValueError):
        select_impl("nope", {})


def test_js_entry_points_exist():
    dg = select_impl("destructive-guard", {})
    gd = select_impl("gated-dev-simple-workflow", {"GD_IMPL": "js"})
    for argv in (dg.gate_hook(), dg.env_guard(), dg.check(), gd.launch(), gd.watch_pr(), gd.notify()):
        assert os.path.isfile(argv[-1]), argv


def test_py_argv_shapes():
    dg = select_impl("destructive-guard", {"GD_IMPL": "py"})
    assert dg.check()[1] == "-I"
    assert dg.check()[-1].endswith("lib/check.py")
    gd = select_impl("gated-dev-simple-workflow", {"GD_IMPL": "py"})
    assert gd.notify()[1].endswith("run-python.sh")
    assert gd.watch_pr()[-1].endswith("scripts/watch_pr.py")


def test_find_python_prefers_env():
    assert find_python({"GATE_INFRA_PYTHON": "/nope", "PATH": os.environ["PATH"]}) == "/nope"


def test_find_python_prefers_314_over_python3(tmp_path):
    _fake(tmp_path, "python3")
    _fake(tmp_path, "python3.14")
    assert find_python({"PATH": str(tmp_path)}).endswith("python3.14")


def test_find_python_falls_back_to_python3(tmp_path):
    _fake(tmp_path, "python3")
    assert find_python({"PATH": str(tmp_path)}).endswith("python3")


def test_find_python_none(tmp_path):
    assert find_python({"PATH": str(tmp_path)}) is None


def test_empty_env_var_is_ignored(tmp_path):
    _fake(tmp_path, "python3")
    assert find_python({"GATE_INFRA_PYTHON": "", "PATH": str(tmp_path)}).endswith("python3")


def test_js_env_without_node_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="node not found on PATH"):
        select_impl("gated-dev-simple-workflow", {"GD_IMPL": "js"}).env()


def test_impl_interpreter_fields():
    py = select_impl("destructive-guard", {})
    assert py.interpreter_var == "GATE_INFRA_PYTHON"
    assert py.unavailable_reason == "unparsable: python unavailable"
    assert py.check_invocation("--config") == f'python3 "{DG}/lib/check.py" --config'


def test_require_new_python_rejects_old(tmp_path):
    from testkit.pythons import require_new_python

    fake = tmp_path / "python3"
    fake.write_text('#!/bin/sh\nfor a; do case "$a" in *version_info*) echo "3.9"; exit 0;; esac; done\necho 3.9\n')
    fake.chmod(0o755)
    with pytest.raises(RuntimeError, match=r"need Python >= 3\.14, found 3\.9 at .*python3; set GATE_INFRA_PYTHON"):
        require_new_python({"PATH": str(tmp_path)})
    with pytest.raises(RuntimeError, match="found nothing"):
        require_new_python({"PATH": str(tmp_path / "none")})


def test_impl_watch_pr_fast_js():
    gd = select_impl("gated-dev-simple-workflow", {"GD_IMPL": "js"})
    argv = gd.watch_pr(fast=True)
    assert argv[:2] == ["node", "--import"]
    assert argv[2].endswith("testkit/_fast_timers.mjs")
    assert argv[3].endswith("scripts/watch-pr.mjs")
    assert gd.watch_pr() == [argv[0], argv[3]]


def test_impl_watch_pr_fast_py_not_yet():
    gd = select_impl("gated-dev-simple-workflow", {"GD_IMPL": "py"})
    with pytest.raises(NotImplementedError):
        gd.watch_pr(fast=True)


def test_gate_hook_is_the_shipped_gate_sh():
    assert select_impl("destructive-guard", {}).gate_hook()[-1].endswith("hooks/gate.sh")
