"""Compare ACM waveforms against ngspice PDK-BSIM golden references."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .waveforms import interpolate_to, load_xy_csv


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    """Root-mean-square error between two arrays."""
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch {a.shape} vs {b.shape}")
    return float(np.sqrt(np.mean(np.square(a - b))))


def compare_to_golden(
    analysis: str,
    ref_csv: Path,
    acm_csv: Path,
) -> dict[str, Any]:
    """Compute analysis metrics of ACM vs golden BSIM CSV waveforms.

    Raises:
        ValueError: On empty/degenerate signals or unsupported analysis.
    """
    x_ref, y_ref = load_xy_csv(ref_csv)
    x_acm, y_acm = load_xy_csv(acm_csv)
    y_on_ref = interpolate_to(x_ref, x_acm, y_acm)
    ref_max = float(np.max(np.abs(y_ref)))
    acm_max = float(np.max(np.abs(y_on_ref)))
    if ref_max <= 0.0:
        raise ValueError(f"degenerate golden reference (max=0) in {ref_csv}")
    if acm_max <= 0.0:
        raise ValueError(
            f"degenerate ACM waveform (max=0) in {acm_csv} "
            "(for HSPICE: check -hdl VA load / PVA flow nodes)"
        )

    if analysis in {"dc", "transient", "temp"}:
        return {
            "n_points": int(len(x_ref)),
            "rmse_linear": rmse(y_ref, y_on_ref),
            "rmse_log": rmse(
                np.log10(np.abs(y_ref) + 1e-18),
                np.log10(np.abs(y_on_ref) + 1e-18),
            ),
            "ref_max": ref_max,
            "acm_max": acm_max,
        }
    if analysis == "ac":
        return {
            "n_points": int(len(x_ref)),
            "rmse_vm": rmse(y_ref, y_on_ref),
            "ref_vm_max": ref_max,
            "acm_vm_max": acm_max,
        }
    if analysis == "noise":
        return {
            "n_points": int(len(x_ref)),
            "rmse_onoise": rmse(y_ref, y_on_ref),
            "ref_onoise_max": ref_max,
            "acm_onoise_max": acm_max,
        }
    raise ValueError(f"unsupported analysis metrics: {analysis!r}")


__all__ = ["compare_to_golden", "rmse"]
