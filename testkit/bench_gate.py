"""Latency of a full hook call, JS (hooks/gate.sh) vs Python (testkit/_gate_py.sh).

Not a test: `uv run python -m testkit.bench_gate --n 200`. Runs the same mixed inputs
(Bash allow, Bash ask, script scan, MCP) through both wrappers with the default packs and
prints p50/p95 per implementation, calls interleaved so both see the same machine load.
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
    wrappers = {
        "js": (["bash", str(DG / "hooks" / "gate.sh")], {}),
        "py": (["bash", str(Path(__file__).resolve().parent / "_gate_py.sh")], {"GATE_INFRA_PYTHON": python}),
    }
    times: dict[str, list[float]] = {k: [] for k in wrappers}
    with tempfile.TemporaryDirectory() as tmp:
        data = inputs(provision_project(Path(tmp)))
        for i in range(n):
            payload = data[i % len(data)]
            for name, (argv, extra) in wrappers.items():
                t = time.perf_counter()
                subprocess.run(argv, input=payload, capture_output=True, env=clean_env(extra), check=True)
                times[name].append((time.perf_counter() - t) * 1000)
    for name, ms in times.items():
        print(f"{name}: n={len(ms)} p50={statistics.median(ms):.1f}ms p95={pct(ms, 0.95):.1f}ms")
    delta = pct(times["py"], 0.95) - pct(times["js"], 0.95)
    print(f"p95 py - js = {delta:+.1f}ms (budget +50ms)")


if __name__ == "__main__":
    main()
