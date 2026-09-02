"""Declarative staged-fit profiles (per model tier)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SUPPORTED_CURVE_SELECTORS: tuple[str, ...] = (
    "all",
    "low_vds",
    "mid_vds",
    "high_vds",
)


@dataclass(frozen=True)
class FitStage:
    """One design-oriented extraction stage."""

    stage_id: str
    free: tuple[str, ...]
    curves: str
    loss_overrides: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.free:
            raise ValueError(f"fit stage {self.stage_id!r}: free must be non-empty")
        if self.curves not in SUPPORTED_CURVE_SELECTORS:
            raise ValueError(
                f"fit stage {self.stage_id!r}: unsupported curves "
                f"{self.curves!r}; known={SUPPORTED_CURVE_SELECTORS}"
            )


@dataclass(frozen=True)
class FitProfile:
    """Ordered staged-fit recipe for one or more model tiers."""

    profile_id: str
    model_tiers: tuple[str, ...]
    stages: tuple[FitStage, ...]

    def stages_for_model(self, free_params: tuple[str, ...]) -> tuple[FitStage, ...]:
        """Return stages whose free parameters are supported by the model."""
        allowed = set(free_params)
        out: list[FitStage] = []
        for stage in self.stages:
            if not all(name in allowed for name in stage.free):
                continue
            out.append(stage)
        if not out:
            raise ValueError(
                f"fit profile {self.profile_id!r} has no applicable stages "
                f"for free_params={free_params!r}"
            )
        return tuple(out)


def load_fit_profile(repo_root: Path, profile_id: str) -> FitProfile:
    """Load ``config/fit_profiles/<profile_id>.json``."""
    path = repo_root / "config/fit_profiles" / f"{profile_id}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"missing fit profile {profile_id!r}: expected {path}"
        )
    payload = json.loads(path.read_text())
    file_id = str(payload.get("profile_id", profile_id))
    if file_id != profile_id:
        raise ValueError(
            f"fit profile id mismatch: file {file_id!r} != requested {profile_id!r}"
        )
    tiers_raw = payload.get("model_tiers")
    if not isinstance(tiers_raw, list) or not tiers_raw:
        raise ValueError(f"fit profile {profile_id!r}: model_tiers must be non-empty")
    stages_raw = payload.get("stages")
    if not isinstance(stages_raw, list) or not stages_raw:
        raise ValueError(f"fit profile {profile_id!r}: stages must be non-empty")
    stages: list[FitStage] = []
    for entry in stages_raw:
        if not isinstance(entry, Mapping):
            raise ValueError(f"fit profile {profile_id!r}: stage must be an object")
        stage_id = str(entry.get("id", ""))
        if not stage_id:
            raise ValueError(f"fit profile {profile_id!r}: stage missing id")
        free_raw = entry.get("free")
        if not isinstance(free_raw, list) or not free_raw:
            raise ValueError(f"fit stage {stage_id!r}: free must be a non-empty list")
        curves = str(entry.get("curves", "all"))
        loss_overrides = entry.get("loss", {})
        if loss_overrides is not None and not isinstance(loss_overrides, Mapping):
            raise ValueError(f"fit stage {stage_id!r}: loss must be an object")
        stages.append(
            FitStage(
                stage_id=stage_id,
                free=tuple(str(n) for n in free_raw),
                curves=curves,
                loss_overrides=dict(loss_overrides or {}),
            )
        )
    return FitProfile(
        profile_id=profile_id,
        model_tiers=tuple(str(t) for t in tiers_raw),
        stages=tuple(stages),
    )


def resolve_fit_profile(
    repo_root: Path,
    *,
    profile_id: str,
    model_tier: str,
    free_params: tuple[str, ...],
) -> FitProfile:
    """Load a profile and verify it applies to ``model_tier``."""
    profile = load_fit_profile(repo_root, profile_id)
    if model_tier not in profile.model_tiers:
        raise ValueError(
            f"fit profile {profile_id!r} does not apply to model tier "
            f"{model_tier!r}; model_tiers={profile.model_tiers!r}"
        )
    return profile


__all__ = [
    "FitStage",
    "FitProfile",
    "SUPPORTED_CURVE_SELECTORS",
    "load_fit_profile",
    "resolve_fit_profile",
]
