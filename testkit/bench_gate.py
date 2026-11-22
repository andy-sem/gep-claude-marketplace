"""Latency of the hook's cheapest full path (hooks/gate.sh on Python), without any network.

Not a test: `uv run python -m testkit.bench_gate --n 200`. Runs the misconfigured path (no
`TYPESAFE_API_KEY`: Python starts, reads the config and prints nothing), which is the fixed cost of
every gated call; a call that reaches Jev adds the request. Prints p50/p95.
"""

import argparse
import json
import statistics
import subprocess
import time

from testkit import DG
from testkit.envs import IsolatedEnv
from testkit.pythons import Pythons


class GateBench:
    """Times full hook calls through hooks/gate.sh."""

    @staticmethod
    def pct(values: list[float], q: float) -> float:
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))]

    @classmethod
    def main(cls) -> None:
        ap = argparse.ArgumentParser()
        ap.add_argument("--n", type=int, default=200)
        n = ap.parse_args().n
        python = Pythons.require_new_python(IsolatedEnv.clean())
        argv = ["bash", str(DG / "hooks" / "gate.sh")]
        data = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls -la"}}).encode()
        times: list[float] = []
        for _ in range(n):
            t = time.perf_counter()
            subprocess.run(argv, input=data, capture_output=True, env=IsolatedEnv.clean({"GATE_INFRA_PYTHON": python}), check=True)
            times.append((time.perf_counter() - t) * 1000)
        print(f"misconfigured path: n={len(times)} p50={statistics.median(times):.1f}ms p95={cls.pct(times, 0.95):.1f}ms")


def main() -> None:
    GateBench.main()


if __name__ == "__main__":
    main()
