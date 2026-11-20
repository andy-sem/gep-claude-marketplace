import pytest

from testkit import DG
from testkit.stubs import (
    check_314_imports_package,
    check_old_python_exit_3,
    check_parses_as_37,
    stub_id,
    stubs_of,
)

STUBS = stubs_of(DG)


@pytest.mark.parametrize("stub", STUBS, ids=stub_id)
def test_stub_parses_as_python_37(stub):
    check_parses_as_37(stub[0])


@pytest.mark.parametrize("stub", STUBS, ids=stub_id)
def test_old_python_gets_exit_3(old_python, stub):
    check_old_python_exit_3(old_python, stub[0])


@pytest.mark.parametrize("stub", STUBS, ids=stub_id)
def test_314_imports_package(tmp_path, stub):
    check_314_imports_package(tmp_path, *stub)
