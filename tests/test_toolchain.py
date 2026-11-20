import pathlib
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_running_on_floor_or_newer():
    assert sys.version_info >= (3, 14)


def test_pyproject_pins_floor():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert cfg["project"]["requires-python"] == ">=3.14"
    assert cfg["project"]["dependencies"] == []
    assert cfg["tool"]["ruff"]["target-version"] == "py314"
    assert (ROOT / ".python-version").read_text().strip() == "3.14"
