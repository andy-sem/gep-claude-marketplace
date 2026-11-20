import os
import stat

import pytest

from testkit.impl import select_impl
from testkit.pythons import find_python

PLUGIN_NAMES = ["destructive-guard", "gated-dev-simple-workflow"]


def _fake(dir_path, name):
    p = dir_path / name
    p.write_text("#!/bin/sh\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


@pytest.mark.parametrize("plugin", PLUGIN_NAMES)
def test_default_is_js_for_both_plugins(plugin):
    assert select_impl(plugin, {}).name == "js"


def test_gd_impl_overrides():
    assert select_impl("destructive-guard", {"GD_IMPL": "py"}).name == "py"


def test_gd_impl_typo_raises():
    with pytest.raises(ValueError, match="GD_IMPL"):
        select_impl("destructive-guard", {"GD_IMPL": "pyhton"})


def test_unknown_plugin_raises():
    with pytest.raises(ValueError):
        select_impl("nope", {})


def test_js_entry_points_exist():
    dg = select_impl("destructive-guard", {"GD_IMPL": "js"})
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
