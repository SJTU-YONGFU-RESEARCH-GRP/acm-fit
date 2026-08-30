"""Repository root discovery for CLI entry points."""

from __future__ import annotations

from pathlib import Path


def release_root() -> Path:
    """Return the acm-fit release repository root (parent of ``src/``)."""
    return Path(__file__).resolve().parents[3]
