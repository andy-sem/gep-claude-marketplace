"""Fixtures shared by the destructive-guard contract tests."""

import json
from pathlib import Path

import pytest

from testkit import DG

# The shipped-rules stand-in (a fixed rule file independent of packs/).
SHIPPED = DG / "tests" / "fixtures" / "rules.json"


@pytest.fixture(scope="session")
def tf_rules(tmp_path_factory) -> Path:
    """One `tf` rule on `terraform apply`, with grep inert."""
    path = tmp_path_factory.mktemp("rules") / "rules.json"
    path.write_text(
        json.dumps(
            {
                "wrappers": [],
                "runners": [],
                "inertPrograms": ["grep"],
                "rules": [{"id": "tf", "kind": "cli-gated", "programs": ["terraform"], "gatedPrefixes": [["apply"]]}],
            }
        )
    )
    return path


@pytest.fixture(scope="session")
def bad_rules(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("rules") / "bad.json"
    path.write_text("{not json")
    return path


@pytest.fixture(scope="session")
def shipped_rules() -> Path:
    return SHIPPED
