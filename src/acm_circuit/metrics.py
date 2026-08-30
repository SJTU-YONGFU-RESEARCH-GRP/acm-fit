"""Circuit benchmark metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from acm_eval.metrics import rmse
from acm_eval.waveforms import interpolate_to, load_xy_csv, wrdata_to_xy


def _wrdata_vin_vout(raw: np.ndarray, path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(vin, vout)`` from ngspice ``wrdata`` with optional index column."""
    if raw.ndim != 2 or raw.shape[1] < 2 or raw.shape[0] < 2:
        raise ValueError(f"expected wrdata matrix in {path}, got {raw.shape}")
    if raw.shape[1] >= 3:
        return raw[:, 1], raw[:, 2]
    return raw[:, 0], raw[:, 1]


def vtc_rmse(ref_csv: Path, acm_csv: Path) -> dict[str, Any]:
    """RMSE of Vout vs Vin for inverter VTC (column 2 vs column 1)."""
    vin_ref, vout_ref = _wrdata_vin_vout(np.loadtxt(ref_csv), ref_csv)
    vin_acm, vout_acm = _wrdata_vin_vout(np.loadtxt(acm_csv), acm_csv)
    vout_on_ref = interpolate_to(vin_ref, vin_acm, vout_acm)
    err = rmse(vout_ref, vout_on_ref)
    return {
        "vout_rmse": err,
        "n_points": int(len(vin_ref)),
    }


def estimate_osc_freq_hz(wave_csv: Path, *, discard_frac: float = 0.5) -> float:
    """Estimate oscillation frequency from transient voltage waveform."""
    t, v = wrdata_to_xy(wave_csv)
    if len(t) < 10:
        raise ValueError(f"transient too short in {wave_csv}")
    i0 = int(len(t) * discard_frac)
    t = t[i0:]
    v = v[i0:]
    v = v - np.mean(v)
    # Zero-crossing based period estimate.
    signs = np.sign(v)
    crossings = np.where(np.diff(signs) != 0)[0]
    if len(crossings) < 4:
        raise ValueError(f"insufficient crossings in {wave_csv}")
    half_periods = np.diff(t[crossings])
    period = 2.0 * float(np.median(half_periods))
    if period <= 0.0:
        raise ValueError(f"invalid period from {wave_csv}")
    return 1.0 / period


def ac_gain_db_rmse(ref_csv: Path, acm_csv: Path) -> dict[str, Any]:
    """RMSE of AC gain in dB."""
    f_ref, g_ref = load_xy_csv(ref_csv)
    f_acm, g_acm = load_xy_csv(acm_csv)
    g_on_ref = interpolate_to(f_ref, f_acm, g_acm)
    ref_db = 20.0 * np.log10(np.abs(g_ref) + 1e-18)
    acm_db = 20.0 * np.log10(np.abs(g_on_ref) + 1e-18)
    return {
        "gain_db_rmse": rmse(ref_db, acm_db),
        "n_points": int(len(f_ref)),
    }


def parse_ngspice_print(path: Path) -> dict[str, float]:
    """Parse ngspice ``print`` output file into name -> value."""
    out: dict[str, float] = {}
    if not path.is_file():
        raise FileNotFoundError(path)
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                out[parts[0].lower()] = float(parts[-1])
            except ValueError:
                continue
    return out


__all__ = [
    "vtc_rmse",
    "estimate_osc_freq_hz",
    "ac_gain_db_rmse",
    "parse_ngspice_print",
]
