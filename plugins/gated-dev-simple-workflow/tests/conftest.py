"""Fixtures of the gated-dev-simple-workflow tests."""

import pytest

from gd_testkit.pythons import Pythons


@pytest.fixture
def old_python() -> str:
    python = Pythons.find_old_python()
    if python is None:
        pytest.skip("no Python < 3.14 available")
    return python
