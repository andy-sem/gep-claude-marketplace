"""Latency of a full hook call (hooks/gate.sh on Python).

Not a test: `uv run python -m testkit.bench_gate --n 200`. Runs mixed inputs
(Bash allow, Bash ask, script scan, MCP) with the default packs and prints p50/p95.
"""

import argparse
import json
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from testkit import DG
from testkit.envs import clean_env
from testkit.projects import provision_project
from testkit.pythons import require_new_python


def inputs(project: Path) -> list[bytes]:
    cwd = str(project)
    calls = [
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        {"tool_name": "Bash", "tool_input": {"command": "git status && git diff --stat"}},
        {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}},
        {"tool_name": "Bash", "tool_input": {"command": "sudo rm -rf build"}},
        {"tool_name": "Bash", "tool_input": {"command": "node scripts/provision-cloud-app-dev.mjs"}},
        {"tool_name": "mcp__db__execute_sql", "tool_input": {"query": "SELECT 1"}},
        {"tool_name": "mcp__db__execute_sql", "tool_input": {"query": "DROP TABLE x"}},
    ]
    return [json.dumps({**c, "cwd": cwd}).encode() for c in calls]


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    n = ap.parse_args().n
    python = require_new_python(clean_env())
    argv = ["bash", str(DG / "hooks" / "gate.sh")]
    times: list[float] = []
    with tempfile.TemporaryDirectory() as tmp:
        data = inputs(provision_project(Path(tmp)))
        for i in range(n):
            t = time.perf_counter()
            subprocess.run(argv, input=data[i % len(data)], capture_output=True, env=clean_env({"GATE_INFRA_PYTHON": python}), check=True)
            times.append((time.perf_counter() - t) * 1000)
    print(f"py: n={len(times)} p50={statistics.median(times):.1f}ms p95={pct(times, 0.95):.1f}ms")


if __name__ == "__main__":
    main()
