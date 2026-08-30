"""Frozen QLAW production champions from qlaw_x promotion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QlawPdkDefault:
    """Recommended QLAW physics tier for one PDK."""

    pdk: str
    physics_tier: str
    stage: str
    method: str
    weighted_err: float
    rationale: str


@dataclass(frozen=True)
class QlawCrossPdkDefault:
    """Cross-PDK QLAW fallback when a single tier is required."""

    physics_tier: str
    stage: str
    method: str
    max_weighted_err: float
    rationale: str


def load_qlaw_defaults(repo_root: Path) -> dict[str, QlawPdkDefault]:
    """Load and validate ``config/qlaw_defaults.json`` per-PDK entries."""
    path = repo_root / "config/qlaw_defaults.json"
    payload = json.loads(path.read_text())
    raw = payload.get("defaults")
    if not raw:
        raise ValueError("defaults missing from qlaw_defaults.json")
    out: dict[str, QlawPdkDefault] = {}
    for pdk, entry in raw.items():
        tier = entry.get("physics_tier")
        stage = entry.get("stage")
        if not tier or not stage:
            raise ValueError(f"qlaw default for {pdk!r} missing physics_tier or stage")
        out[str(pdk)] = QlawPdkDefault(
            pdk=str(pdk),
            physics_tier=str(tier),
            stage=str(stage),
            method=str(entry.get("method", "")),
            weighted_err=float(entry["weighted_err"]),
            rationale=str(entry.get("rationale", "")),
        )
    return out


def frozen_qlaw_tiers(repo_root: Path) -> frozenset[str]:
    """Return registry ids promoted from experimental to production."""
    path = repo_root / "config/qlaw_defaults.json"
    payload = json.loads(path.read_text())
    raw = payload.get("frozen_tiers")
    if not raw:
        raise ValueError("frozen_tiers missing from qlaw_defaults.json")
    return frozenset(str(tier_id) for tier_id in raw)


def cross_pdk_qlaw_default(repo_root: Path) -> QlawCrossPdkDefault:
    """Return the cross-PDK QLAW fallback tier."""
    path = repo_root / "config/qlaw_defaults.json"
    payload = json.loads(path.read_text())
    raw = payload.get("cross_pdk")
    if not raw:
        raise ValueError("cross_pdk missing from qlaw_defaults.json")
    tier = raw.get("physics_tier")
    stage = raw.get("stage")
    if not tier or not stage:
        raise ValueError("cross_pdk missing physics_tier or stage")
    return QlawCrossPdkDefault(
        physics_tier=str(tier),
        stage=str(stage),
        method=str(raw.get("method", "")),
        max_weighted_err=float(raw["max_weighted_err"]),
        rationale=str(raw.get("rationale", "")),
    )


def default_qlaw_tier(repo_root: Path, pdk: str) -> str:
    """Return the recommended QLAW physics tier id for ``pdk``."""
    defaults = load_qlaw_defaults(repo_root)
    if pdk not in defaults:
        known = ", ".join(sorted(defaults))
        raise ValueError(f"unknown pdk {pdk!r}; known: {known}")
    return defaults[pdk].physics_tier


__all__ = [
    "QlawCrossPdkDefault",
    "QlawPdkDefault",
    "cross_pdk_qlaw_default",
    "default_qlaw_tier",
    "frozen_qlaw_tiers",
    "load_qlaw_defaults",
]
