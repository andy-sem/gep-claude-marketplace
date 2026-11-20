"""Subprocess environments that never inherit the developer's gate settings."""

import os
import re
from collections.abc import Mapping

_DROP = re.compile(r"^(GATE_|TYPESAFE_)")


def clean_env(*overlays: Mapping[str, str]) -> dict[str, str]:
    """os.environ minus GATE_*, TYPESAFE_* and CLAUDE_PROJECT_DIR, then each overlay in order."""
    env = {k: v for k, v in os.environ.items() if not _DROP.match(k) and k != "CLAUDE_PROJECT_DIR"}
    for overlay in overlays:
        env.update({k: str(v) for k, v in overlay.items()})
    return env
