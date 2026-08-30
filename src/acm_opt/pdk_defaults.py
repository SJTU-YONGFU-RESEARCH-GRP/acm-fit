"""Per-PDK recommended physics tier from acm_x promotion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PdkDefault:
    """Recommended physics tier for one PDK."""

    pdk: str
    physics_tier: str
    stage: str
    rationale: str


def load_pdk_defaults(repo_root: Path) -> dict[str, PdkDefault]:
    """Load and validate ``config/pdk_defaults.json``."""
    path = repo_root / "config/pdk_defaults.json"
    payload = json.loads(path.read_text())
    raw = payload.get("defaults")
    if not raw:
        raise ValueError("defaults missing from pdk_defaults.json")
    out: dict[str, PdkDefault] = {}
    for pdk, entry in raw.items():
        tier = entry.get("physics_tier")
        if not tier:
            raise ValueError(f"pdk {pdk!r} missing physics_tier")
        out[str(pdk)] = PdkDefault(
            pdk=str(pdk),
            physics_tier=str(tier),
            stage=str(entry.get("stage", "")),
            rationale=str(entry.get("rationale", "")),
        )
    return out


def default_physics_tier(repo_root: Path, pdk: str) -> str:
    """Return the recommended physics tier id for ``pdk``."""
    defaults = load_pdk_defaults(repo_root)
    if pdk not in defaults:
        known = ", ".join(sorted(defaults))
        raise ValueError(f"unknown pdk {pdk!r}; known: {known}")
    return defaults[pdk].physics_tier


__all__ = ["PdkDefault", "default_physics_tier", "load_pdk_defaults"]
