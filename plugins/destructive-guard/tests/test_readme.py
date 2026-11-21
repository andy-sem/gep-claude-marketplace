"""README stays in sync with the code (port of readme.test.mjs)."""

import re

import pytest

from testkit import DG

README = (DG / "README.md").read_text()
# Variables the hook wrapper and the tests use internally; not user settings.
INTERNAL = {"GATE_RUN", "GATE_DONE_FILE", "GATE_INFRA_PYTHON"}
ENV_NAME = re.compile(r"\b(?:GATE|TYPESAFE)_[A-Z_]*[A-Z]\b")


def env_names() -> list[str]:
    files = [p for p in (DG / "lib").rglob("*") if p.is_file() and p.suffix == ".py"]
    files += [p for p in (DG / "hooks").iterdir() if p.is_file()]
    names = {m for p in files for m in ENV_NAME.findall(p.read_text())}
    return sorted(names - INTERNAL)


def test_readme_documents_every_env_variable():
    names = env_names()
    assert len(names) >= 10, "found the variables"
    assert [n for n in names if f"`{n}`" not in README] == []


@pytest.mark.parametrize("path", sorted([*(DG / "packs").glob("*.json"), *(DG / "jev").glob("*.json")]), ids=lambda p: p.name)
def test_readme_lists_every_pack_and_jev_prompt(path):
    assert f"`{path.stem}`" in README
