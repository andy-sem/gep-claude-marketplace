"""Shared helpers for the repo's Python tests."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGINS = REPO / "plugins"
DG = PLUGINS / "destructive-guard"
GD = PLUGINS / "gated-dev-simple-workflow"

__all__ = ["DG", "GD", "PLUGINS", "REPO"]
