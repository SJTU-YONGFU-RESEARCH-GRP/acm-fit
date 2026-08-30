"""Generate waveform overlay plots for regression reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

_REF_GRAY = "#4d4d4d"
_ACM_RED = "#c41e3a"


def _read_xy_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    raw = np.loadtxt(path, delimiter=",", skiprows=1)
    if raw.ndim != 2 or raw.shape[1] < 2:
        raise ValueError(f"expected x,y columns in {path}")
    return raw[:, 0], raw[:, 1]


def _analysis_axes(analysis: str) -> tuple[str, str, bool, bool]:
    """Return x-label, y-label, log_x, log_y for one analysis."""
    if analysis == "dc":
        return "Vg (V)", "Id (A)", False, True
    if analysis == "ac":
        return "Frequency (Hz)", "|V| (V)", True, False
    if analysis == "noise":
        return "Frequency (Hz)", "Output noise (V²/Hz)", True, True
    if analysis == "transient":
        return "Time (s)", "Id (A)", True, False
    if analysis == "temp":
        return "Temperature (°C)", "Id (A)", False, True
    raise ValueError(f"unsupported analysis for plot: {analysis!r}")


def write_xy_overlay_plot(
    *,
    ref_csv: Path,
    acm_csv: Path,
    out_path: Path,
    title: str,
    analysis: str,
    ref_label: str = "Reference",
    acm_label: str = "ACM fit",
) -> Path:
    """Overlay reference vs ACM ``x,y`` CSV waveforms."""
    x_ref, y_ref = _read_xy_csv(ref_csv)
    x_acm, y_acm = _read_xy_csv(acm_csv)
    x_label, y_label, log_x, log_y = _analysis_axes(analysis)

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    if log_x:
        ax.loglog(x_ref, np.abs(y_ref), color=_REF_GRAY, linewidth=2.0, label=ref_label)
        ax.loglog(x_acm, np.abs(y_acm), color=_ACM_RED, linewidth=2.0, linestyle="--", label=acm_label)
    elif log_y:
        ax.semilogy(x_ref, np.abs(y_ref), color=_REF_GRAY, linewidth=2.0, label=ref_label)
        ax.semilogy(x_acm, np.abs(y_acm), color=_ACM_RED, linewidth=2.0, linestyle="--", label=acm_label)
    else:
        ax.plot(x_ref, y_ref, color=_REF_GRAY, linewidth=2.0, label=ref_label)
        ax.plot(x_acm, y_acm, color=_ACM_RED, linewidth=2.0, linestyle="--", label=acm_label)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def write_xy_solo_plot(
    *,
    acm_csv: Path,
    out_path: Path,
    title: str,
    analysis: str,
    acm_label: str = "ACM fit",
) -> Path:
    """Plot a single ACM ``x,y`` CSV waveform (no reference overlay)."""
    x_acm, y_acm = _read_xy_csv(acm_csv)
    x_label, y_label, log_x, log_y = _analysis_axes(analysis)

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    if log_x and log_y:
        ax.loglog(x_acm, np.abs(y_acm), color=_ACM_RED, linewidth=2.0, label=acm_label)
    elif log_x:
        ax.semilogx(x_acm, np.abs(y_acm), color=_ACM_RED, linewidth=2.0, label=acm_label)
    elif log_y:
        ax.semilogy(x_acm, np.abs(y_acm), color=_ACM_RED, linewidth=2.0, label=acm_label)
    else:
        ax.plot(x_acm, y_acm, color=_ACM_RED, linewidth=2.0, label=acm_label)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def write_bench_waveform_plots(
    *,
    results_dir: Path,
    model: str,
    predict_rows: Sequence[Mapping[str, Any]],
) -> list[Path]:
    """Write ``plots/<pdk>/bench_<analysis>.png`` for successful predict benches."""
    written: list[Path] = []
    for row in sorted(
        predict_rows,
        key=lambda x: (x["pdk"], x["simulator"], x["analysis"]),
    ):
        if not bool(row.get("ok")):
            continue
        pdk = str(row["pdk"])
        analysis = str(row["analysis"])
        simulator = str(row["simulator"])
        acm_csv = results_dir / model / "benches" / pdk / simulator / analysis / "acm.csv"
        if not acm_csv.is_file():
            continue
        ref_csv = results_dir / "golden" / pdk / "ref" / analysis / "ref.csv"
        if ref_csv.is_file():
            continue
        out = results_dir / model / "plots" / pdk / f"bench_{analysis}.png"
        write_xy_solo_plot(
            acm_csv=acm_csv,
            out_path=out,
            title=f"{pdk} / {analysis} ({simulator}, ACM-only)",
            analysis=analysis,
            acm_label=str(row.get("model", model)),
        )
        written.append(out)
    return written


def write_eval_overlay_plots(
    *,
    results_dir: Path,
    model: str,
    eval_rows: Sequence[Mapping[str, Any]],
    ref_label: str = "BSIM golden",
) -> list[Path]:
    """Write ``plots/<pdk>/eval_<analysis>.png`` for successful eval jobs."""
    written: list[Path] = []
    for row in sorted(
        eval_rows,
        key=lambda x: (x["pdk"], x["simulator"], x["analysis"]),
    ):
        if str(row.get("status", "")).lower() != "ok":
            continue
        pdk = str(row["pdk"])
        analysis = str(row["analysis"])
        simulator = str(row["simulator"])
        ref_csv = results_dir / "golden" / pdk / "ref" / analysis / "ref.csv"
        acm_csv = results_dir / model / "eval" / pdk / simulator / analysis / "acm.csv"
        if not ref_csv.is_file() or not acm_csv.is_file():
            continue
        out = results_dir / model / "plots" / pdk / f"eval_{analysis}.png"
        write_xy_overlay_plot(
            ref_csv=ref_csv,
            acm_csv=acm_csv,
            out_path=out,
            title=f"{pdk} / {analysis} ({simulator})",
            analysis=analysis,
            ref_label=ref_label,
            acm_label=f"{model}",
        )
        written.append(out)
    return written


__all__ = [
    "write_bench_waveform_plots",
    "write_eval_overlay_plots",
    "write_xy_overlay_plot",
    "write_xy_solo_plot",
]
