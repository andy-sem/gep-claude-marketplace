"""Contract: hooks/env-guard.sh (port of env-guard.test.mjs)."""

import json
import shutil
import subprocess

import pytest

from testkit.envs import IsolatedEnv


def status(argv, file_path, env=None, tool="Read"):
    proc = subprocess.run(
        argv,
        input=json.dumps({"tool_name": tool, "tool_input": {"file_path": file_path}}),
        capture_output=True,
        text=True,
        env=IsolatedEnv.clean(env or {}),
        check=False,
    )
    return proc.returncode


@pytest.mark.parametrize("tool", ["Read", "Edit", "Write"])
@pytest.mark.parametrize("path", ["/p/.env", "/p/.env.local", "/p/apps/web/.env.production"])
def test_blocks_env_files(impl, tool, path):
    assert status(impl.env_guard(), path, tool=tool) == 2


@pytest.mark.parametrize("path", ["/p/.env.example", "/p/src/index.ts", "/p/README.md", ""])
def test_allows_example_and_ordinary_files(impl, path):
    assert status(impl.env_guard(), path) == 0


def test_works_without_jq(impl, tmp_path):
    # A PATH holding only the tools the script needs, so jq cannot be found.
    for tool in ("cat", "sed", "head"):
        (tmp_path / tool).symlink_to(shutil.which(tool))
    argv = ["/bin/bash", *impl.env_guard()[1:]]
    env = {"PATH": str(tmp_path)}
    assert status(argv, "/p/.env", env) == 2
    assert status(argv, "/p/.env.example", env) == 0
    assert status(argv, "/p/src/a.ts", env) == 0
