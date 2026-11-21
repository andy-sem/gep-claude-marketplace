"""Runner for the watcher tests: every time.sleep returns at once.

`python -I _fast_sleep.py <script> [args...]` appends each requested delay (milliseconds, one
per line) to the file named by GD_TEST_SLEEP_LOG, then runs <script> as __main__ so its own
version check and path logic run unchanged.
"""

import os
import runpy
import sys
import time


def _sleep(seconds: float) -> None:
    log = os.environ.get("GD_TEST_SLEEP_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(f"{round(seconds * 1000)}\n")


time.sleep = _sleep
target = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(target, run_name="__main__")
