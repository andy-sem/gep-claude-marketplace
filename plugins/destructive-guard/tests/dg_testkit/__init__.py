"""Test helpers of destructive-guard."""

from pathlib import Path

DG = Path(__file__).resolve().parents[2]
REPO = DG.parents[1]

__all__ = ["DG", "REPO"]
