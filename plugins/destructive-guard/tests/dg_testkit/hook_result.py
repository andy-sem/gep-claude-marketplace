from dataclasses import dataclass


@dataclass(frozen=True)
class HookResult:
    """Exit status and stdout of one gate hook run."""

    status: int
    stdout: str
