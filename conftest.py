"""Root conftest: fixtures shared by repo-level and plugin tests."""

import pytest

from testkit.jev_mock import JevMock
from testkit.pythons import Pythons


@pytest.fixture
def old_python() -> str:
    python = Pythons.find_old_python()
    if python is None:
        pytest.skip("no Python < 3.14 available")
    return python


@pytest.fixture
def jev():
    """A local Jev mock; `jev.url`, `jev.answer(...)`, `jev.bodies`, `jev.hits`."""
    with JevMock() as mock:
        yield mock
