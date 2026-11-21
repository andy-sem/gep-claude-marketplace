"""Result of a finished child process."""

from typing import NamedTuple


class CompletedRun(NamedTuple):
    """Captured stdout and stderr of a finished child process."""

    stdout: str
    stderr: str
