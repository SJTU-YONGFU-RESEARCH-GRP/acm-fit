"""Configurable fit loss: DC Id modes + optional AC/noise multi-objective terms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


SUPPORTED_ID_MODES = ("absolute", "relative", "huber")


@dataclass(frozen=True)
class LossPolicy:
    """Policy for the scalar objective minimized during ACM fitting.

    Attributes:
        id_mode: DC residual mode (`absolute`, `relative`, or `huber`).
        weight_linear: Weight on linear-domain DC residual.
        weight_log: Weight on log10-domain DC residual.
        huber_delta: Huber threshold (linear Id domain); used when
            ``id_mode=huber``.
        region_vt_width_v: Half-width (V) of VT-centered boost window; ``0``
            disables region weighting.
        region_vt_boost: Multiplier for residuals inside the VT window.
        weight_dc: Weight of the DC term in the composite objective.
        weight_ac: Weight of normalized AC ``|v(d)|`` RMSE.
        weight_noise: Weight of normalized noise ``onoise`` RMSE.
        weight_temp: Weight of normalized temp-sweep Id RMSE.
        optuna_trials: Number of TPE trials.
        refine_starts: Number of L-BFGS-B starts from top Optuna trials.
        refine_maxiter: Max iterations per L-BFGS-B start.
    """

    id_mode: str = "absolute"
    weight_linear: float = 0.4
    weight_log: float = 0.6
    huber_delta: float = 1.0e-4
    region_vt_width_v: float = 0.0
    region_vt_boost: float = 2.0
    weight_dc: float = 1.0
    weight_ac: float = 0.0
    weight_noise: float = 0.0
    weight_temp: float = 0.0
    optuna_trials: int = 1000
    refine_starts: int = 3
    refine_maxiter: int = 15

    def __post_init__(self) -> None:
        """Validate policy fields."""
        if self.id_mode not in SUPPORTED_ID_MODES:
            raise ValueError(
                f"unsupported id_mode {self.id_mode!r}; "
                f"known={SUPPORTED_ID_MODES}"
            )
        if self.weight_linear < 0.0 or self.weight_log < 0.0:
            raise ValueError("weight_linear/weight_log must be >= 0")
        if self.weight_linear + self.weight_log <= 0.0:
            raise ValueError("weight_linear + weight_log must be > 0")
        if self.huber_delta <= 0.0:
            raise ValueError(f"huber_delta must be > 0, got {self.huber_delta}")
        if self.region_vt_width_v < 0.0:
            raise ValueError("region_vt_width_v must be >= 0")
        if self.region_vt_boost < 1.0:
            raise ValueError("region_vt_boost must be >= 1")
        for name, value in (
            ("weight_dc", self.weight_dc),
            ("weight_ac", self.weight_ac),
            ("weight_noise", self.weight_noise),
            ("weight_temp", self.weight_temp),
        ):
            if value < 0.0:
                raise ValueError(f"{name} must be >= 0")
        if (
            self.weight_dc
            + self.weight_ac
            + self.weight_noise
            + self.weight_temp
            <= 0.0
        ):
            raise ValueError(
                "at least one of weight_dc/ac/noise/temp must be > 0"
            )
        if self.optuna_trials < 1:
            raise ValueError("optuna_trials must be >= 1")
        if self.refine_starts < 0:
            raise ValueError("refine_starts must be >= 0")
        if self.refine_maxiter < 1:
            raise ValueError("refine_maxiter must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        """Serialize policy for cards / ablation reports."""
        return {
            "id_mode": self.id_mode,
            "weight_linear": self.weight_linear,
            "weight_log": self.weight_log,
            "huber_delta": self.huber_delta,
            "region_vt_width_v": self.region_vt_width_v,
            "region_vt_boost": self.region_vt_boost,
            "weight_dc": self.weight_dc,
            "weight_ac": self.weight_ac,
            "weight_noise": self.weight_noise,
            "weight_temp": self.weight_temp,
            "optuna_trials": self.optuna_trials,
            "refine_starts": self.refine_starts,
            "refine_maxiter": self.refine_maxiter,
        }


def loss_policy_from_mapping(raw: Mapping[str, Any]) -> LossPolicy:
    """Build :class:`LossPolicy` from a JSON mapping (fail on unknown keys)."""
    known = set(LossPolicy.__dataclass_fields__)
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"unknown LossPolicy keys: {unknown}")
    return LossPolicy(**{k: raw[k] for k in known if k in raw})


def _point_weights(
    vg: np.ndarray,
    *,
    vt0: float,
    width_v: float,
    boost: float,
) -> np.ndarray:
    """Per-point weights; boost points near ``vt0`` when ``width_v > 0``."""
    w = np.ones(len(vg), dtype=float)
    if width_v > 0.0:
        mask = np.abs(vg - vt0) <= width_v
        w[mask] = boost
    return w


def _huber_sq(residual: np.ndarray, delta: float) -> np.ndarray:
    """Huber loss mapped to a squared-error-like quantity for RMSE."""
    abs_r = np.abs(residual)
    return np.where(
        abs_r <= delta,
        np.square(residual),
        delta * (2.0 * abs_r - delta),
    )


def dc_curve_residuals(
    vg: np.ndarray,
    id_ref: np.ndarray,
    id_acm: np.ndarray,
    *,
    policy: LossPolicy,
    vt0: float,
) -> tuple[float, float, float]:
    """Return ``(rmse_linear, rmse_log, dc_loss)`` for one Id–Vg curve."""
    if id_ref.shape != id_acm.shape or vg.shape != id_ref.shape:
        raise ValueError(
            f"shape mismatch vg={vg.shape} ref={id_ref.shape} acm={id_acm.shape}"
        )
    eps = 1e-18
    weights = _point_weights(
        vg,
        vt0=vt0,
        width_v=policy.region_vt_width_v,
        boost=policy.region_vt_boost,
    )
    wsum = float(np.sum(weights))
    if wsum <= 0.0:
        raise ValueError("point weights sum to zero")

    if policy.id_mode == "absolute":
        lin_res = id_ref - id_acm
    elif policy.id_mode == "relative":
        lin_res = (id_ref - id_acm) / (np.abs(id_ref) + eps)
    elif policy.id_mode == "huber":
        lin_res = id_ref - id_acm
    else:
        raise ValueError(policy.id_mode)

    if policy.id_mode == "huber":
        lin_term = float(
            np.sqrt(np.sum(weights * _huber_sq(lin_res, policy.huber_delta)) / wsum)
        )
    else:
        lin_term = float(np.sqrt(np.sum(weights * np.square(lin_res)) / wsum))

    log_res = np.log10(np.abs(id_ref) + eps) - np.log10(np.abs(id_acm) + eps)
    log_term = float(np.sqrt(np.sum(weights * np.square(log_res)) / wsum))

    # Report absolute RMSE always for cards (independent of id_mode).
    rmse_linear = float(np.sqrt(np.mean(np.square(id_ref - id_acm))))
    rmse_log = float(np.sqrt(np.mean(np.square(log_res))))
    dc_loss = policy.weight_linear * lin_term + policy.weight_log * log_term
    return rmse_linear, rmse_log, dc_loss


def composite_objective(
    *,
    dc_loss: float,
    ac_rmse: float | None,
    noise_rmse: float | None,
    temp_rmse: float | None,
    ref_vm_max: float | None,
    ref_onoise_max: float | None,
    ref_temp_max: float | None,
    policy: LossPolicy,
) -> float:
    """Combine DC / AC / noise / temp terms into one scalar objective."""
    total = policy.weight_dc * dc_loss
    if policy.weight_ac > 0.0:
        if ac_rmse is None or ref_vm_max is None or ref_vm_max <= 0.0:
            raise ValueError("AC term enabled but ac_rmse/ref_vm_max missing")
        total += policy.weight_ac * (ac_rmse / ref_vm_max)
    if policy.weight_noise > 0.0:
        if noise_rmse is None or ref_onoise_max is None or ref_onoise_max <= 0.0:
            raise ValueError(
                "noise term enabled but noise_rmse/ref_onoise_max missing"
            )
        total += policy.weight_noise * (noise_rmse / ref_onoise_max)
    if policy.weight_temp > 0.0:
        if temp_rmse is None or ref_temp_max is None or ref_temp_max <= 0.0:
            raise ValueError(
                "temp term enabled but temp_rmse/ref_temp_max missing"
            )
        total += policy.weight_temp * (temp_rmse / ref_temp_max)
    return float(total)


# Named ablation presets (data-driven; selected by name in scripts).
ABLATION_PRESETS: dict[str, LossPolicy] = {
    "baseline": LossPolicy(
        id_mode="absolute",
        weight_linear=0.4,
        weight_log=0.6,
        weight_dc=1.0,
        weight_ac=0.0,
        weight_noise=0.0,
        optuna_trials=30,
        refine_starts=3,
        refine_maxiter=12,
    ),
    "log_heavy": LossPolicy(
        id_mode="absolute",
        weight_linear=0.2,
        weight_log=0.8,
        weight_dc=1.0,
        weight_ac=0.0,
        weight_noise=0.0,
        optuna_trials=30,
        refine_starts=3,
        refine_maxiter=12,
    ),
    "lin_heavy": LossPolicy(
        id_mode="absolute",
        weight_linear=0.7,
        weight_log=0.3,
        weight_dc=1.0,
        weight_ac=0.0,
        weight_noise=0.0,
        optuna_trials=30,
        refine_starts=3,
        refine_maxiter=12,
    ),
    "relative": LossPolicy(
        id_mode="relative",
        weight_linear=0.5,
        weight_log=0.5,
        weight_dc=1.0,
        weight_ac=0.0,
        weight_noise=0.0,
        optuna_trials=30,
        refine_starts=3,
        refine_maxiter=12,
    ),
    "region_vt": LossPolicy(
        id_mode="absolute",
        weight_linear=0.4,
        weight_log=0.6,
        region_vt_width_v=0.15,
        region_vt_boost=3.0,
        weight_dc=1.0,
        weight_ac=0.0,
        weight_noise=0.0,
        optuna_trials=30,
        refine_starts=3,
        refine_maxiter=12,
    ),
    "huber": LossPolicy(
        id_mode="huber",
        weight_linear=0.5,
        weight_log=0.5,
        huber_delta=5.0e-5,
        weight_dc=1.0,
        weight_ac=0.0,
        weight_noise=0.0,
        optuna_trials=30,
        refine_starts=3,
        refine_maxiter=12,
    ),
    "multi_obj": LossPolicy(
        id_mode="absolute",
        weight_linear=0.4,
        weight_log=0.6,
        weight_dc=1.0,
        weight_ac=0.0,
        weight_noise=0.0,
        weight_temp=0.0,
        optuna_trials=35,
        refine_starts=3,
        refine_maxiter=15,
    ),
}


__all__ = [
    "SUPPORTED_ID_MODES",
    "LossPolicy",
    "loss_policy_from_mapping",
    "dc_curve_residuals",
    "composite_objective",
    "ABLATION_PRESETS",
]
