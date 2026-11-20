"""Root conftest: fixtures shared by repo-level and plugin tests."""

import os

import pytest

from testkit import PLUGINS
from testkit.impl import Impl, select_impl
from testkit.jev_mock import JevMock
from testkit.pythons import find_old_python


@pytest.fixture
def impl(request) -> Impl:
    """The implementation under test for the plugin that owns this test file."""
    try:
        plugin = request.path.resolve().relative_to(PLUGINS).parts[0]
    except ValueError:
        raise pytest.UsageError("the impl fixture is only available to tests under plugins/") from None
    return select_impl(plugin, os.environ)


@pytest.fixture
def old_python() -> str:
    python = find_old_python()
    if python is None:
        pytest.skip("no Python < 3.14 available")
    return python


@pytest.fixture
def jev():
    """A local Jev mock; `jev.url`, `jev.answer(...)`, `jev.bodies`, `jev.hits`."""
    with JevMock() as mock:
        yield mock
