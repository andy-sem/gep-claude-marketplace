"""Runner for the watcher tests: every time.sleep returns at once.

`python -I _fast_sleep.py <script> [args...]` appends each requested delay (milliseconds, one
per line) to the file named by GD_TEST_SLEEP_LOG, then runs <script> as __main__ so its own
version check and path logic run unchanged.
"""

import os
import runpy
import sys
import time


class FastSleep:
    """Patches time.sleep to log the delay instead of waiting, then runs a target script."""

    target: str = ""

    @staticmethod
    def sleep(seconds: float) -> None:
        log = os.environ.get("GD_TEST_SLEEP_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as handle:
                handle.write(f"{round(seconds * 1000)}\n")

    @classmethod
    def run(cls, argv: list[str]) -> None:
        time.sleep = cls.sleep
        cls.target = argv[0]
        sys.argv = argv
        runpy.run_path(cls.target, run_name="__main__")


if __name__ == "__main__":
    FastSleep.run(sys.argv[1:])
