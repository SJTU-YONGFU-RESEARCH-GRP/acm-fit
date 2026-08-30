"""Instance-parameter bounds and SPICE formatting for ACM fits.

Bounds are keyed by parameter name (physics), not by model id.

Golden fit policy (see ``PLAN.md`` §2.4): only **DC parameters** are optimized.
"""

from __future__ import annotations

from typing import Mapping

from acm_golden import GoldenDevice
from acm_opt.models import ModelSpec

# Parameters allowed in ``ModelSpec.free_params`` during golden DC fit.
DC_FIT_PARAMS: frozenset[str] = frozenset({"VT0", "IS", "n", "sigma", "zeta"})

# Search bounds for VA instance parameters (DC fit + fixed non-DC defaults).
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "VT0": (0.4, 1.0),
    "IS": (1e-8, 3e-5),
    "n": (1.0, 3.0),
    "sigma": (0.0, 0.08),
    "zeta": (1e-3, 0.08),
    "tox": (1.0e-9, 2.0e-8),
    "LD": (1.0e-9, 2.0e-7),
    "Cj0": (1.0e-4, 5.0e-2),
    "Cj0sw": (1.0e-4, 5.0e-2),
    "xd_mj": (0.1, 1.0),
    "phi_zero": (0.3, 1.2),
    "xj": (5.0e-8, 5.0e-7),
    "N_ot": (1.0e10, 1.0e14),
    "alphaVT0": (-2.0e-3, 0.0),
    "alphaIS": (0.5, 3.0),
    "alphasigma": (0.0, 2.0e-6),
    "alphazeta": (0.0, 2.0e-3),
}

# Optuna samples these on a log scale.
LOG_SCALE_PARAMS: frozenset[str] = frozenset(
    {"IS", "tox", "LD", "Cj0", "Cj0sw", "xj", "N_ot"}
)


def bounds_for_model(model: ModelSpec, width_m: float) -> dict[str, tuple[float, float]]:
    """Return search bounds for ``model.free_params`` (+ optional W)."""
    out: dict[str, tuple[float, float]] = {}
    for name in model.free_params:
        if name not in PARAM_BOUNDS:
            raise ValueError(
                f"{model.name}: no PARAM_BOUNDS entry for free param {name!r}"
            )
        out[name] = PARAM_BOUNDS[name]
    out["W"] = (0.5 * width_m, 2.0 * width_m)
    return out


def expand_instance_params(
    model: ModelSpec,
    free: Mapping[str, float],
    golden: GoldenDevice,
) -> dict[str, float]:
    """Expand free values into a full instance dict for simulation."""
    missing = [name for name in model.free_params if name not in free]
    if missing:
        raise ValueError(f"{model.name}: free dict missing {missing}")
    params: dict[str, float] = {
        name: float(free[name]) for name in model.free_params
    }
    params["W"] = float(free["W"]) if "W" in free else golden.width_m
    params["L"] = golden.length_m
    params["m"] = 1.0
    for key, value in model.instance_fixed.items():
        params[key] = float(value)
    return params


def format_spice_instance_params(
    model: ModelSpec,
    card: Mapping[str, float],
    *,
    width_m: float,
    length_m: float,
) -> str:
    """Format instance parameter assignments for SPICE/Spectre decks."""
    width = float(card["W"]) if "W" in card else width_m
    length = float(card["L"]) if "L" in card else length_m
    parts = [f"W={width:.8g}", f"L={length:.8g}", "m=1"]
    for name in model.free_params:
        if name not in card:
            raise ValueError(f"{model.name}: card missing free param {name!r}")
        value = card[name]
        if name == "type":
            parts.append(f"type={int(value)}")
        else:
            parts.append(f"{name}={float(value):.8g}")
    for key, value in model.instance_fixed.items():
        if key in model.free_params:
            continue
        actual = card[key] if key in card else value
        if key == "type" or isinstance(value, int):
            parts.append(f"{key}={int(actual)}")
        else:
            parts.append(f"{key}={float(actual):.8g}")
    if (
        "type" in card
        and "type" not in model.free_params
        and "type" not in model.instance_fixed
    ):
        parts.append(f"type={int(card['type'])}")
    return " ".join(parts)


# VA defaults for unlocks not present in an earlier-stage card.
VA_DEFAULTS: dict[str, float] = {
    "tox": 4.0e-9,
    "LD": 30.0e-9,
    "Cj0": 4.0e-3,
    "Cj0sw": 4.0e-3,
    "xd_mj": 0.5,
    "phi_zero": 0.6,
    "xj": 150.0e-9,
    "N_ot": 1.0e12,
    "alphaVT0": -0.4e-3,
    "alphaIS": 1.5,
    "alphasigma": 0.3e-6,
    "alphazeta": 0.2e-3,
}


def fill_missing_free_params(
    model: ModelSpec,
    parameters: Mapping[str, float],
) -> dict[str, float]:
    """Fill missing ``model.free_params`` from :data:`VA_DEFAULTS` (fail if none)."""
    out = {k: float(v) for k, v in parameters.items()}
    for name in model.free_params:
        if name in out:
            continue
        if name not in VA_DEFAULTS:
            raise ValueError(
                f"{model.name}: card missing {name!r} and no VA_DEFAULTS entry"
            )
        out[name] = float(VA_DEFAULTS[name])
    return out


def validate_dc_fit_params(model: ModelSpec) -> None:
    """Fail if ``model.free_params`` includes non-DC instance parameters."""
    bad = [name for name in model.free_params if name not in DC_FIT_PARAMS]
    if bad:
        raise ValueError(
            f"{model.name}: golden fit allows DC params only {sorted(DC_FIT_PARAMS)!r}; "
            f"unsupported free param(s): {bad}"
        )


def validate_dc_fit_policy(policy: object) -> None:
    """Fail if fit loss includes AC/noise/temp terms (DC Id fit only)."""
    from acm_opt.loss import LossPolicy

    if not isinstance(policy, LossPolicy):
        raise TypeError(f"expected LossPolicy, got {type(policy).__name__}")
    for name in ("weight_ac", "weight_noise", "weight_temp"):
        if float(getattr(policy, name)) > 0.0:
            raise ValueError(
                f"golden fit is DC-only; set {name}=0 (got {getattr(policy, name)!r})"
            )


__all__ = [
    "DC_FIT_PARAMS",
    "PARAM_BOUNDS",
    "LOG_SCALE_PARAMS",
    "VA_DEFAULTS",
    "bounds_for_model",
    "expand_instance_params",
    "format_spice_instance_params",
    "fill_missing_free_params",
    "validate_dc_fit_params",
    "validate_dc_fit_policy",
]
