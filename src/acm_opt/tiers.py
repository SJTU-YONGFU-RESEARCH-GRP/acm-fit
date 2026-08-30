"""Load ACM / QLAW physics tier specification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class TierBranches:
    """Active equation branches for one physics tier."""

    dc_core: bool
    intrinsic_charge: bool
    overlap_cap: bool
    junction_bottom: bool
    junction_sidewall: bool
    noise: bool
    temp_dc: bool


@dataclass(frozen=True)
class TierSpec:
    """One entry from ``config/acm_tier_spec.json``."""

    tier_id: str
    generation: int
    module: str
    va_path: Path | None
    osdi_path: Path | None
    parent: str | None
    branches: TierBranches
    doc_path: Path | None
    status: str
    dc_fit_params: tuple[str, ...]


def _parse_branches(raw: Mapping[str, bool]) -> TierBranches:
    required = (
        "dc_core",
        "intrinsic_charge",
        "overlap_cap",
        "junction_bottom",
        "junction_sidewall",
        "noise",
        "temp_dc",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"tier branches missing keys: {missing}")
    if not raw["dc_core"]:
        raise ValueError("dc_core must be true for every tier")
    return TierBranches(
        dc_core=bool(raw["dc_core"]),
        intrinsic_charge=bool(raw["intrinsic_charge"]),
        overlap_cap=bool(raw["overlap_cap"]),
        junction_bottom=bool(raw["junction_bottom"]),
        junction_sidewall=bool(raw["junction_sidewall"]),
        noise=bool(raw["noise"]),
        temp_dc=bool(raw["temp_dc"]),
    )


def load_tier_spec(repo_root: Path) -> dict[str, TierSpec]:
    """Load and validate the tier specification."""
    path = repo_root / "config/acm_tier_spec.json"
    payload = json.loads(path.read_text())
    dc_fit = tuple(payload["dc_fit_params"])
    expected = ("VT0", "IS", "n", "sigma")
    if dc_fit != expected:
        raise ValueError(f"dc_fit_params must be {expected!r}, got {dc_fit!r}")
    out: dict[str, TierSpec] = {}
    for tier_id, raw in payload["tiers"].items():
        va_rel = raw.get("va")
        osdi_rel = raw.get("osdi")
        doc_rel = raw.get("doc")
        tier_dc = tuple(raw.get("dc_fit_params", dc_fit))
        if tier_id.startswith("acm4") and tier_dc != dc_fit:
            raise ValueError(f"tier {tier_id!r} must use global dc_fit_params")
        if (tier_id == "qlaw" or tier_id.startswith("qlaw_")) and tier_dc != dc_fit:
            raise ValueError(f"tier {tier_id!r} must use global dc_fit_params")
        out[tier_id] = TierSpec(
            tier_id=tier_id,
            generation=int(raw.get("generation", 4)),
            module=str(raw["module"]),
            va_path=repo_root / va_rel if va_rel else None,
            osdi_path=repo_root / osdi_rel if osdi_rel else None,
            parent=raw.get("parent"),
            branches=_parse_branches(raw["branches"]),
            doc_path=repo_root / doc_rel if doc_rel else None,
            status=str(raw.get("status", "active")),
            dc_fit_params=tier_dc,
        )
    return out


def legacy_tier_map(repo_root: Path) -> dict[str, str]:
    """Return legacy registry id → target physics tier id."""
    path = repo_root / "config/acm_tier_spec.json"
    payload = json.loads(path.read_text())
    raw = payload.get("legacy_registry_map")
    if not raw:
        return {}
    return {str(k): str(v) for k, v in raw.items()}


__all__ = [
    "TierBranches",
    "TierSpec",
    "load_tier_spec",
    "legacy_tier_map",
]
