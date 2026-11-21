"""Command line of the PR watcher.

Prints one JSON line (`watch_pr.py --state <abs>/<ticketsDir>/<KEY>/state.json`).
Outcomes: feedback, merged, closed (exit 0: the JSON line says which, and Claude Code
reports any non-zero exit of a background command as a failure), error (exit 1),
usage (exit 2). stdout carries the final JSON line only; progress and errors go to stderr.
"""

import json
import os
import sys
from typing import Any, ClassVar

from gated_dev.watch.watcher import PrWatcher


class WatchPrCli:
    """Parses the arguments, runs the watcher and prints its outcome."""

    EXIT: ClassVar[dict[str, int]] = {"feedback": 0, "merged": 0, "closed": 0, "error": 1, "usage": 2}

    @staticmethod
    def _parse_args(argv: list[str]) -> dict:
        if len(argv) != 2 or argv[0] != "--state":
            return {"error": "usage: watch_pr.py --state <abs path>/state.json"}
        if not os.path.isabs(argv[1]):
            return {"error": "--state must be an absolute path"}
        return {"state_path": argv[1]}

    @classmethod
    def main(cls, argv: list[str] | None = None, **deps: Any) -> int:
        """Prints exactly one JSON line on stdout and returns the exit code."""
        out = deps.pop("out", None) or (lambda line: sys.stdout.write(f"{line}\n"))
        parsed = cls._parse_args(sys.argv[1:] if argv is None else argv)
        if "error" in parsed:
            out(json.dumps({"outcome": "usage", "message": parsed["error"]}))
            return cls.EXIT["usage"]
        result = PrWatcher(**deps).watch(state_path=parsed["state_path"])
        out(json.dumps(result))
        return cls.EXIT[result["outcome"]]


def main(argv: list[str] | None = None, **deps: Any) -> int:
    return WatchPrCli.main(argv, **deps)
