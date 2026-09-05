#!/usr/bin/env python3
"""Generate LASCAS paper figures from acm-fit benchmark results."""

from __future__ import annotations

from acm.cli._root import release_root

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from acm.plot_style import (
    ANNOT_SIZE,
    BAR_COLOR,
    BAR_EDGE_COLOR,
    BAR_EDGE_WIDTH,
    CBAR_LABEL_SIZE,
    COLOR_ACCENT,
    COLOR_CORNER_FF,
    COLOR_PRIMARY,
    COLOR_REFERENCE,
    COLOR_SECONDARY,
    FIGSIZE_COLUMN,
    FIGSIZE_COLUMN_BAR,
    FIGSIZE_COLUMN_HEATMAP,
    FIGSIZE_COLUMN_RUNTIME,
    FIGSIZE_COLUMN_IDVG,
    FIGSIZE_COLUMN_PTM_PARAMS,
    FIGSIZE_COLUMN_SQUARE,
    LABEL_SIZE,
    LEGEND_SIZE,
    LINEWIDTH_MAIN,
    LINEWIDTH_SECONDARY,
    MARKER_SIZE_MAIN,
    MARKER_SIZE_SECONDARY,
    SCATTER_SIZE_LARGE,
    SPINE_WIDTH,
    TICK_SIZE,
    TITLE_SIZE,
    apply_style,
    ensure_rcparams,
    save_figure,
    series_color,
    set_axis_labels,
)

NODE_ORDER = [
    ("ptm180", 180),
    ("ptm130", 130),
    ("ptm90", 90),
    ("ptm65", 65),
    ("ptm45", 45),
    ("ptm32", 32),
    ("ptm22", 22),
]

CORNER_PARAMS = ("VT0", "IS", "n", "zeta")

PTM_FIT_PARAMS = (
    ("VT0", r"$V_{T0}$ (mV)", 1e3),
    ("IS", r"$I_S$ (nA)", 1e9),
    ("n", r"$n$", 1.0),
    ("sigma", r"$\sigma$", 1.0),
    ("zeta", r"$\zeta$", 1.0),
)

CORNER_DISPLAY = {
    "tt": "TT",
    "typical": "Typ.",
    "ss": "SS",
    "ff": "FF",
}

STRATEGY_LABELS = {
    "optuna": "Optuna (TPE)",
    "optuna_cmaes": "Optuna (CMA-ES)",
    "optuna_gp": "Optuna (GP-BO)",
    "optuna_qmc": "Optuna (QMC)",
    "optuna_random": "Random",
    "differential_evolution": "Diff. evolution",
    "dual_annealing": "Dual annealing",
    "lbfgsb": "L-BFGS-B only",
    "staged": "Staged",
    "staged_optuna": "Staged-Optuna",
    "staged_cmaes": "Staged-CMA-ES",
}

STRATEGY_FAMILY = {
    "optuna": "Optuna",
    "optuna_cmaes": "Optuna",
    "optuna_gp": "Optuna",
    "optuna_qmc": "Optuna",
    "optuna_random": "Optuna",
    "differential_evolution": "SciPy global",
    "dual_annealing": "SciPy global",
    "staged": "Staged",
    "staged_optuna": "Staged",
    "staged_cmaes": "Staged",
    "lbfgsb": "Local only",
}

STRATEGY_FAMILY_COLORS = {
    "Optuna": COLOR_PRIMARY,
    "SciPy global": COLOR_SECONDARY,
    "Staged": COLOR_ACCENT,
    "Local only": COLOR_REFERENCE,
}

STRATEGY_TARGET_ORDER = (
    "gf180mcu_typical",
    "sky130_tt",
    "sky130_ss",
    "sky130_ff",
    "ptm180",
    "ptm130",
    "ptm90",
    "ptm65",
    "ptm45",
    "ptm32",
    "ptm22",
    "custom_1vds_sat",
    "custom_2vds",
    "custom_3vds_std",
    "custom_sparse_vg",
)

# Corner re-exports (custom_gf180_typ, custom_sky130_ss/ff, custom_ptm22) share golden
# curves with commercial/PTM rows and are omitted from the heatmap to avoid duplicates.

STRATEGY_TARGET_LABELS = {
    "gf180mcu_typical": "GF180 typ",
    "sky130_tt": "sky130 TT",
    "sky130_ss": "sky130 SS",
    "sky130_ff": "sky130 FF",
    "ptm180": "PTM 180 nm",
    "ptm130": "PTM 130 nm",
    "ptm90": "PTM 90 nm",
    "ptm65": "PTM 65 nm",
    "ptm45": "PTM 45 nm",
    "ptm32": "PTM 32 nm",
    "ptm22": "PTM 22 nm",
    "custom_1vds_sat": "1-VDS sat",
    "custom_2vds": "2-VDS",
    "custom_3vds_std": "3-VDS std",
    "custom_sparse_vg": "Sparse $V_g$",
}

STRATEGY_BENCH_DIRS = (
    "commercial",
    "ptm",
    "strategy_bench",
)

# Models included in LASCAS strategy / PTM comparison figures.
PAPER_FIT_MODELS = (
    "acm4",
    "acm5",
    "qlaw_gm_j14",
)

MODEL_LABELS = {
    "acm4": "ACM-4",
    "acm5": "ACM-5",
    "qlaw_gm_j14": "QLAW",
}

MODEL_COLORS = {
    "acm4": COLOR_ACCENT,
    "acm5": COLOR_PRIMARY,
    "qlaw_gm_j14": COLOR_SECONDARY,
}

MODEL_MARKERS = {
    "acm4": "s",
    "acm5": "o",
    "qlaw_gm_j14": "^",
}

STRATEGY_ANNOT_OFFSETS: dict[str, tuple[int, int, str, str]] = {
    # dx, dy (pt), ha, va — keep labels inside axes (above low-y points, right of left edge)
    "optuna_cmaes": (0, -20, "right", "bottom"),
    "differential_evolution": (10, -5, "left", "bottom"),
    "optuna": (0, 10, "left", "bottom"),
    "optuna_gp": (50, -20, "right", "bottom"),
    "optuna_random": (-15, -5, "right", "bottom"),
    "dual_annealing": (12, -2, "left", "bottom"),
    "optuna_qmc": (14, 2, "left", "bottom"),
    "staged_optuna": (14, 2, "left", "top"),
    "staged_cmaes": (14, 6, "left", "bottom"),
    "staged": (14, 4, "left", "center"),
    "lbfgsb": (18, 0, "left", "center"),
}


def _runtime_annotation_offset(row: dict) -> tuple[int, int, str, str]:
    """Nudge labels away from axes when static offsets are insufficient."""
    x = float(row["mean_fit_wall_s"])
    y = float(row["mean_weighted_error"])
    strategy = row["strategy"]
    explicit = strategy in STRATEGY_ANNOT_OFFSETS
    dx, dy, ha, va = STRATEGY_ANNOT_OFFSETS.get(strategy, (8, 5, "left", "bottom"))
    # Only auto-correct default offsets; explicit per-strategy tables win.
    if not explicit and y < 0.08 and dy < 0:
        dy = 20
        va = "bottom"
    if not explicit and x < 70 and dx < 0:
        dx = 14
        ha = "left"
    return dx, dy, ha, va

SKY130_IDVG_CORNERS = (
    ("sky130_tt", "TT", COLOR_PRIMARY),
    ("sky130_ff", "FF", COLOR_CORNER_FF),
    ("sky130_ss", "SS", COLOR_SECONDARY),
)


def _load_fit_cards(fit_dir: Path) -> list[dict]:
    cards: list[dict] = []
    for path in sorted(fit_dir.glob("*.json")):
        if path.name == "fit_summary.json":
            continue
        payload = json.loads(path.read_text())
        if "parameters" in payload:
            cards.append(payload)
    return cards


def plot_ptm_scaling(ptm_dir: Path, out: Path) -> None:
    ensure_rcparams()
    fit_dir = ptm_dir / "acm5" / "fit"
    cards = {str(c["pdk"]): c for c in _load_fit_cards(fit_dir)}
    xs, ys = [], []
    for pdk, nm in NODE_ORDER:
        if pdk in cards:
            xs.append(nm)
            ys.append(float(cards[pdk]["weighted_error"]))
    if not xs:
        raise FileNotFoundError(f"no PTM fit cards in {fit_dir}")

    fig, ax = plt.subplots(figsize=FIGSIZE_COLUMN)
    ax.plot(
        xs,
        ys,
        "o-",
        color=COLOR_PRIMARY,
        linewidth=LINEWIDTH_MAIN,
        markersize=MARKER_SIZE_MAIN,
        markerfacecolor="white",
        markeredgewidth=1.0,
        label="ACM-5 baseline",
    )
    set_axis_labels(
        ax,
        title="Technology scaling (PTM BSIM reference)",
        xlabel="Technology node (nm)",
        ylabel="Weighted DC fit error",
    )
    ax.set_xscale("log")
    ax.invert_xaxis()
    apply_style(ax)
    ax.legend(fontsize=LEGEND_SIZE)
    save_figure(fig, out, dpi=300)
    print(f"wrote {out}")


def plot_ptm_params(ptm_dir: Path, out: Path) -> None:
    """PTM scaling: shared DC params (ACM-5) + weighted error for ACM-4/5/QLAW."""
    ensure_rcparams()
    cards_by_model: dict[str, dict[str, dict]] = {}
    for model in PAPER_FIT_MODELS:
        fit_dir = ptm_dir / model / "fit"
        if not fit_dir.is_dir():
            continue
        cards = {str(c["pdk"]): c for c in _load_fit_cards(fit_dir)}
        if cards:
            cards_by_model[model] = cards
    if "acm5" not in cards_by_model:
        raise FileNotFoundError(f"no ACM-5 PTM fit cards under {ptm_dir}")
    if not cards_by_model:
        raise FileNotFoundError(f"no PTM fit cards under {ptm_dir}")

    node_ticks = [NODE_ORDER[0][1], NODE_ORDER[-1][1]]  # 180 nm, 22 nm
    acm5_cards = cards_by_model["acm5"]

    fig, axes = plt.subplots(3, 2, figsize=FIGSIZE_COLUMN_PTM_PARAMS, sharex=True)
    for ax_idx, (param, label, scale) in enumerate(PTM_FIT_PARAMS):
        ax = axes.flat[ax_idx]
        xs, ys = [], []
        for pdk, nm in NODE_ORDER:
            if pdk in acm5_cards and param in acm5_cards[pdk]["parameters"]:
                xs.append(nm)
                ys.append(float(acm5_cards[pdk]["parameters"][param]) * scale)
        if not xs:
            raise KeyError(f"parameter {param} missing from ACM-5 PTM fit cards")
        ax.plot(
            xs,
            ys,
            "o-",
            color=COLOR_PRIMARY,
            linewidth=LINEWIDTH_SECONDARY,
            markersize=MARKER_SIZE_SECONDARY,
            markerfacecolor="white",
            markeredgewidth=1.0,
        )
        set_axis_labels(ax, title=label)
        ax.set_xscale("log")
        ax.invert_xaxis()
        apply_style(ax)
        ax.tick_params(axis="y", labelleft=True, labelright=False)

    ax_err = axes.flat[5]
    for model, cards in cards_by_model.items():
        err_x, err_y = [], []
        for pdk, nm in NODE_ORDER:
            if pdk in cards:
                err_x.append(nm)
                err_y.append(float(cards[pdk]["weighted_error"]))
        if not err_x:
            continue
        ax_err.plot(
            err_x,
            err_y,
            f"{MODEL_MARKERS[model]}-",
            color=MODEL_COLORS[model],
            linewidth=LINEWIDTH_SECONDARY,
            markersize=MARKER_SIZE_SECONDARY,
            markerfacecolor="white",
            markeredgewidth=1.0,
            label=MODEL_LABELS[model],
        )
    set_axis_labels(ax_err, title="Wt. error")
    ax_err.set_xscale("log")
    ax_err.invert_xaxis()
    apply_style(ax_err)
    ax_err.tick_params(axis="y", labelleft=True, labelright=False)
    if len(cards_by_model) > 1:
        ax_err.legend(
            fontsize=LEGEND_SIZE - 1,
            frameon=False,
            loc="best",
            handlelength=1.6,
        )

    for ax in axes.flat[:4]:
        ax.tick_params(labelbottom=False)
    for ax in axes[2, :]:
        ax.set_xticks(node_ticks)
        ax.set_xticklabels([str(t) for t in node_ticks])
    fig.supxlabel("Technology node (nm)", fontsize=LABEL_SIZE, fontweight="bold", y=0.02)
    fig.subplots_adjust(hspace=0.50, wspace=0.58, top=0.98, bottom=0.14, left=0.13, right=0.98)

    save_figure(fig, out, dpi=300, layout="none")
    print(f"wrote {out}")


def plot_corner_params(commercial_dir: Path, out: Path) -> None:
    ensure_rcparams()
    cards = _load_fit_cards(commercial_dir / "acm5" / "fit")
    by_base: dict[str, list[dict]] = {}
    for card in cards:
        base = str(card.get("base_pdk") or card["pdk"].rsplit("_", 1)[0])
        corner = str(card.get("corner") or card["pdk"].rsplit("_", 1)[-1])
        by_base.setdefault(base, []).append({**card, "corner": corner})

    if not by_base:
        raise FileNotFoundError("no corner fit cards found")

    fig, axes = plt.subplots(2, 2, figsize=FIGSIZE_COLUMN_SQUARE, sharex=False)
    param_labels = {
        "VT0": r"$V_{T0}$ (mV)",
        "IS": r"$I_S$ (nA)",
        "n": r"$n$",
        "zeta": r"$\zeta$",
    }
    scales = {
        "VT0": 1e3,
        "IS": 1e9,
        "n": 1.0,
        "zeta": 1.0,
    }

    for idx, (ax, param) in enumerate(zip(axes.flat, CORNER_PARAMS)):
        for base_idx, base_pdk in enumerate(sorted(by_base)):
            group = sorted(by_base[base_pdk], key=lambda c: c["corner"])
            corners = [
                CORNER_DISPLAY.get(c["corner"], c["corner"].upper())
                for c in group
            ]
            vals = [float(c["parameters"][param]) * scales[param] for c in group]
            ax.plot(
                corners,
                vals,
                "o-",
                linewidth=LINEWIDTH_SECONDARY,
                markersize=MARKER_SIZE_SECONDARY,
                color=series_color(base_idx),
                label=base_pdk,
            )
        set_axis_labels(
            ax,
            title=param_labels[param],
            xlabel="Process corner" if idx >= 2 else None,
        )
        apply_style(ax)
    axes[0, 0].legend(fontsize=LEGEND_SIZE)
    fig.subplots_adjust(hspace=0.42, wspace=0.32, top=0.98, bottom=0.10, left=0.13, right=0.98)

    save_figure(fig, out, dpi=300, layout="none")
    print(f"wrote {out}")


def _read_golden_curve(path: Path) -> tuple[np.ndarray, np.ndarray]:
    lines = path.read_text().strip().splitlines()
    vg, ids = [], []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) >= 2:
            vg.append(float(parts[0]))
            ids.append(float(parts[1]))
    return np.array(vg), np.array(ids)


def plot_idvg_sky130_corners(commercial_dir: Path, vds_tag: str, out: Path) -> None:
    ensure_rcparams()
    vds_v = float(vds_tag.replace("p", "."))
    fig, (ax_lin, ax_log) = plt.subplots(
        2,
        1,
        figsize=FIGSIZE_COLUMN_IDVG,
        sharex=True,
    )
    lw = LINEWIDTH_SECONDARY

    for target, corner_label, fit_color in SKY130_IDVG_CORNERS:
        golden_csv = commercial_dir / "golden" / target / f"idvg_vds_{vds_tag}.csv"
        acm_csv = commercial_dir / "acm5" / "benches" / target / "ngspice" / "dc" / "acm.csv"
        if not golden_csv.is_file():
            raise FileNotFoundError(golden_csv)
        if not acm_csv.is_file():
            raise FileNotFoundError(acm_csv)

        vg_g, id_g = _read_golden_curve(golden_csv)
        vg_a, id_a = _read_golden_curve(acm_csv)
        # Per-corner BSIM (dotted) and ACM-5 (solid) share color so overlays read correctly.
        bsim_label = f"BSIM {corner_label}"
        acm_label = f"ACM-5 {corner_label}"

        ax_lin.plot(
            vg_g,
            id_g * 1e6,
            color=fit_color,
            linewidth=lw,
            linestyle=":",
            label=bsim_label,
        )
        ax_lin.plot(
            vg_a,
            id_a * 1e6,
            color=fit_color,
            linewidth=lw,
            linestyle="-",
            label=acm_label,
        )

        mask_g = id_g > 0
        mask_a = id_a > 0
        ax_log.semilogy(
            vg_g[mask_g],
            id_g[mask_g],
            color=fit_color,
            linewidth=lw,
            linestyle=":",
            label=bsim_label,
        )
        ax_log.semilogy(
            vg_a[mask_a],
            id_a[mask_a],
            color=fit_color,
            linewidth=lw,
            linestyle="-",
            label=acm_label,
        )

    set_axis_labels(
        ax_lin,
        title=f"sky130 corners, $V_{{DS}}$ = {vds_v:g} V (linear)",
        xlabel=r"$V_g$ (V)",
        ylabel=r"$I_d$ ($\mu$A)",
    )
    apply_style(ax_lin)
    set_axis_labels(
        ax_log,
        title=f"sky130 corners, $V_{{DS}}$ = {vds_v:g} V (log)",
        xlabel=r"$V_g$ (V)",
        ylabel=r"$I_d$ (A)",
    )
    apply_style(ax_log)
    ax_lin.legend(fontsize=max(LEGEND_SIZE - 1, 6), loc="upper left", ncol=2)
    ax_log.legend(fontsize=max(LEGEND_SIZE - 1, 6), loc="lower right", ncol=2)
    fig.supxlabel(r"$V_g$ (V)", fontsize=LABEL_SIZE, fontweight="bold", y=0.02)
    ax_lin.set_xlabel("")
    ax_log.set_xlabel("")
    fig.subplots_adjust(hspace=0.25, top=0.97, bottom=0.12, left=0.14, right=0.98)

    save_figure(fig, out, dpi=300, layout="none")
    print(f"wrote {out}")


def plot_idvg_overlay(commercial_dir: Path, target: str, vds_tag: str, out: Path) -> None:
    ensure_rcparams()
    golden_csv = commercial_dir / "golden" / target / f"idvg_vds_{vds_tag}.csv"
    acm_csv = commercial_dir / "acm5" / "benches" / target / "ngspice" / "dc" / "acm.csv"
    if not golden_csv.is_file():
        raise FileNotFoundError(golden_csv)
    if not acm_csv.is_file():
        raise FileNotFoundError(acm_csv)

    vg_g, id_g = _read_golden_curve(golden_csv)
    vg_a, id_a = _read_golden_curve(acm_csv)

    vds_v = float(vds_tag.replace("p", "."))
    fig, (ax_lin, ax_log) = plt.subplots(
        2,
        1,
        figsize=FIGSIZE_COLUMN_IDVG,
        sharex=True,
    )
    lw = LINEWIDTH_SECONDARY

    ax_lin.plot(vg_g, id_g * 1e6, color=COLOR_REFERENCE, linewidth=lw, label="BSIM reference")
    ax_lin.plot(
        vg_a,
        id_a * 1e6,
        color=COLOR_SECONDARY,
        linewidth=lw,
        linestyle=":",
        label="ACM-5 fit",
    )
    set_axis_labels(
        ax_lin,
        title=f"sky130 TT, $V_{{DS}}$ = {vds_v:g} V (linear)",
        xlabel=r"$V_g$ (V)",
        ylabel=r"$I_d$ ($\mu$A)",
    )
    apply_style(ax_lin)

    mask_g = id_g > 0
    mask_a = id_a > 0
    ax_log.semilogy(
        vg_g[mask_g],
        id_g[mask_g],
        color=COLOR_REFERENCE,
        linewidth=lw,
        label="BSIM reference",
    )
    ax_log.semilogy(
        vg_a[mask_a],
        id_a[mask_a],
        color=COLOR_SECONDARY,
        linewidth=lw,
        linestyle=":",
        label="ACM-5 fit",
    )
    set_axis_labels(
        ax_log,
        title=f"sky130 TT, $V_{{DS}}$ = {vds_v:g} V (log)",
        xlabel=r"$V_g$ (V)",
        ylabel=r"$I_d$ (A)",
    )
    apply_style(ax_log)
    ax_lin.legend(fontsize=LEGEND_SIZE, loc="upper left")
    ax_log.legend(fontsize=LEGEND_SIZE, loc="lower right")
    fig.supxlabel(r"$V_g$ (V)", fontsize=LABEL_SIZE, fontweight="bold", y=0.02)
    ax_lin.set_xlabel("")
    ax_log.set_xlabel("")
    fig.subplots_adjust(hspace=0.25, top=0.97, bottom=0.12, left=0.14, right=0.98)

    save_figure(fig, out, dpi=300, layout="none")
    print(f"wrote {out}")


def plot_overview_diagram(out: Path) -> None:
    """Fig. 1: motivation, status quo gap, and acm-fit contribution (wireframe)."""
    ensure_rcparams()
    from matplotlib.patches import FancyBboxPatch

    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5.5)
    ax.axis("off")

    def rbox(
        x: float,
        y: float,
        w: float,
        h: float,
        label: str,
        *,
        edge: str = COLOR_PRIMARY,
        linestyle: str = "-",
        fontsize: float = 8,
    ) -> None:
        patch = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            fill=False,
            linewidth=SPINE_WIDTH,
            edgecolor=edge,
            linestyle=linestyle,
        )
        ax.add_patch(patch)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=fontsize)

    def arrow(x0: float, y0: float, x1: float, y1: float) -> None:
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops=dict(arrowstyle="->", lw=1.2, color=COLOR_REFERENCE),
        )

    # Zone A: Open PDK
    ax.text(1.1, 5.15, "(A) Open PDK layer", fontsize=9, fontweight="bold", color=COLOR_REFERENCE)
    rbox(0.2, 4.35, 1.1, 0.55, "sky130", edge=COLOR_REFERENCE)
    rbox(1.45, 4.35, 1.1, 0.55, "GF180MCU", edge=COLOR_REFERENCE)
    arrow(1.3, 4.62, 2.85, 4.62)
    arrow(2.0, 4.62, 2.85, 4.62)
    rbox(2.85, 4.25, 1.55, 0.75, "BSIM\nreference", edge=COLOR_REFERENCE)

    # Zone B: Status quo
    ax.text(0.35, 3.55, "(B) Status quo (gap)", fontsize=9, fontweight="bold", color=COLOR_SECONDARY)
    gap = FancyBboxPatch(
        (0.15, 0.55),
        5.0,
        2.85,
        boxstyle="round,pad=0.04,rounding_size=0.1",
        fill=False,
        linewidth=SPINE_WIDTH,
        edgecolor=COLOR_SECONDARY,
        linestyle="--",
    )
    ax.add_patch(gap)
    rbox(0.35, 2.55, 1.45, 0.75, "Manual ACM\ncorner fits", edge=COLOR_SECONDARY, fontsize=7.5)
    rbox(1.95, 2.55, 1.45, 0.75, "Interactive\ndemo (GUI)", edge=COLOR_SECONDARY, fontsize=7.5)
    rbox(3.55, 2.55, 1.45, 0.75, "Equation-based\n(ATMAD)", edge=COLOR_SECONDARY, fontsize=7.5)
    ax.text(0.55, 2.35, "not batchable", fontsize=6.5, color=COLOR_SECONDARY)
    ax.text(2.15, 2.35, "not headless", fontsize=6.5, color=COLOR_SECONDARY)
    ax.text(3.75, 2.35, "no BSIM netlists", fontsize=6.5, color=COLOR_SECONDARY)
    rbox(0.55, 1.35, 4.35, 0.75, "ACM-5 (UFSC): public Verilog-A, manual extraction", edge=COLOR_ACCENT, fontsize=7.5)
    ax.text(4.55, 1.55, "X", fontsize=12, color=COLOR_SECONDARY, ha="center", fontweight="bold")

    # Motivation banner
    rbox(0.35, 0.65, 4.75, 0.55, "Motivation: reproducible fitting from arbitrary $I_d$-$V_g$ data", edge=COLOR_REFERENCE, fontsize=7.5)
    arrow(5.15, 2.5, 5.75, 2.5)

    # Zone C: acm-fit
    ax.text(5.95, 3.55, "(C) acm-fit contribution", fontsize=9, fontweight="bold", color=COLOR_PRIMARY)
    contrib = FancyBboxPatch(
        (5.75, 0.55),
        5.9,
        2.85,
        boxstyle="round,pad=0.04,rounding_size=0.1",
        fill=False,
        linewidth=SPINE_WIDTH + 0.5,
        edgecolor=COLOR_PRIMARY,
        linestyle="-",
    )
    ax.add_patch(contrib)
    rbox(5.95, 2.35, 2.55, 1.0, "Platform\n• golden corpus\n• commercial / PTM / custom\n• predict & eval reports", fontsize=7)
    rbox(8.7, 2.35, 2.55, 1.0, "Hybrid DC engine\n• staged extraction\n• Optuna + refine\n• benchmark mode", fontsize=7)
    arrow(7.5, 2.85, 8.7, 2.85)
    rbox(6.55, 0.75, 3.9, 0.65, "Fitted Verilog-A card (ACM-5 baseline) + regression reports", edge=COLOR_PRIMARY, fontsize=7.5)
    arrow(7.2, 2.35, 7.2, 1.42)
    arrow(9.95, 2.35, 8.9, 1.42)

    ax.set_title(
        "Open-source compact-model fitting landscape and acm-fit",
        fontsize=TITLE_SIZE,
        fontweight="bold",
        pad=12,
    )
    save_figure(fig, out, dpi=300)
    print(f"wrote {out}")


def plot_pipeline_diagram(out: Path) -> None:
    """Fig. 2: operational workflow — three reference lanes and five batch stages."""
    ensure_rcparams()
    from matplotlib.patches import FancyBboxPatch

    fig, ax = plt.subplots(figsize=(11, 3.9))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 3.9)
    ax.axis("off")

    def rbox(
        x: float,
        y: float,
        w: float,
        h: float,
        label: str,
        *,
        edge: str = COLOR_PRIMARY,
        fontsize: float = 8,
        fontweight: str = "normal",
        linestyle: str = "-",
        linewidth: float | None = None,
    ) -> None:
        patch = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            fill=False,
            linewidth=linewidth or SPINE_WIDTH,
            edgecolor=edge,
            linestyle=linestyle,
        )
        ax.add_patch(patch)
        ax.text(
            x + w / 2,
            y + h / 2,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            fontweight=fontweight,
        )

    def arrow(x0: float, y0: float, x1: float, y1: float) -> None:
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops=dict(arrowstyle="->", lw=1.2, color=COLOR_REFERENCE),
        )

    lane_y = 2.85
    lane_h = 0.68
    lane_w = 1.2
    lane_gap = 0.18
    lanes = [
        (0.2, "Commercial\nsky130 / GF180", COLOR_PRIMARY),
        (0.2 + lane_w + lane_gap, "PTM scaling\n180–22 nm", COLOR_PRIMARY),
        (0.2 + 2 * (lane_w + lane_gap), "Custom BYOD\nuser CSV", COLOR_ACCENT),
    ]
    for x, label, color in lanes:
        rbox(x, lane_y, lane_w, lane_h, label, edge=color, fontsize=7.5)

    corpus_x = 4.35
    corpus_w = 1.45
    corpus_h = 0.95
    corpus_y = 2.72
    rbox(corpus_x, corpus_y, corpus_w, corpus_h, "Golden\n$I_d$-$V_g$ corpus", fontsize=8)
    for x, _, _ in lanes:
        arrow(x + lane_w, lane_y + lane_h / 2, corpus_x, corpus_y + corpus_h / 2)

    ax.text(0.2, 3.68, "Reference lanes", fontsize=9, fontweight="bold", color=COLOR_PRIMARY)

    batch_y = 0.35
    batch_h = 2.05
    batch = FancyBboxPatch(
        (0.15, batch_y),
        10.7,
        batch_h,
        boxstyle="round,pad=0.04,rounding_size=0.1",
        fill=False,
        linewidth=SPINE_WIDTH,
        edgecolor=COLOR_PRIMARY,
    )
    ax.add_patch(batch)
    ax.text(0.28, 2.2, "Batch driver (five stages)", fontsize=9, fontweight="bold", color=COLOR_PRIMARY)

    stage_y = 1.05
    stage_h = 0.9
    stage_w = 1.12
    stage_gap = 0.1
    stage_x0 = 0.35
    stages: list[tuple[str, str, str, str]] = [
        ("1", "Golden\ncapture", COLOR_REFERENCE, "-"),
        ("2", "Hybrid DC\nextraction", COLOR_SECONDARY, "-"),
        ("3", "Predict\nbenches", COLOR_PRIMARY, "-"),
        ("4", "Eval vs\nreference", COLOR_PRIMARY, "--"),
        ("5", "Structured\nreports", COLOR_PRIMARY, "-"),
    ]
    for idx, (num, label, edge, linestyle) in enumerate(stages):
        x = stage_x0 + idx * (stage_w + stage_gap)
        is_fit = num == "2"
        rbox(
            x,
            stage_y,
            stage_w,
            stage_h,
            f"{num}. {label}",
            edge=edge,
            fontsize=7.6 if not is_fit else 7.8,
            fontweight="bold" if is_fit else "normal",
            linestyle=linestyle,
            linewidth=SPINE_WIDTH + (0.5 if is_fit else 0),
        )
        if idx:
            prev_x = stage_x0 + (idx - 1) * (stage_w + stage_gap) + stage_w
            arrow(prev_x + 0.03, stage_y + stage_h / 2, x - 0.03, stage_y + stage_h / 2)

    arrow(corpus_x + corpus_w / 2, corpus_y, corpus_x + corpus_w / 2, 2.38)
    arrow(corpus_x + corpus_w / 2, 2.38, stage_x0 + stage_w / 2, 2.38)
    arrow(stage_x0 + stage_w / 2, 2.38, stage_x0 + stage_w / 2, stage_y + stage_h)

    fit_x = stage_x0 + stage_w + stage_gap
    eval_x = stage_x0 + 3 * (stage_w + stage_gap)
    ax.text(
        fit_x + stage_w / 2,
        stage_y - 0.12,
        "staged profiles, Optuna + refine, warm-start waves",
        fontsize=6.3,
        color=COLOR_SECONDARY,
        ha="center",
        va="top",
    )
    ax.text(
        eval_x + stage_w / 2,
        stage_y - 0.12,
        "optional when BSIM exists",
        fontsize=6.3,
        color=COLOR_REFERENCE,
        ha="center",
        va="top",
    )

    out_x = stage_x0 + 5 * (stage_w + stage_gap) + 0.08
    out_w = 1.55
    rbox(
        out_x,
        0.72,
        out_w,
        1.38,
        "Artifacts\n"
        r"$\bullet$ fitted Verilog-A card" "\n"
        r"$\bullet$ $I_d$-$V_g$ overlays" "\n"
        r"$\bullet$ corner / strategy tables",
        fontsize=7.0,
    )
    last_stage_x = stage_x0 + 4 * (stage_w + stage_gap) + stage_w
    arrow(last_stage_x + 0.03, stage_y + stage_h / 2, out_x, stage_y + stage_h / 2)

    ax.set_title(
        "Operational acm-fit workflow (three reference lanes)",
        fontsize=TITLE_SIZE,
        fontweight="bold",
        pad=8,
    )
    save_figure(fig, out, dpi=300)
    print(f"wrote {out}")


def _write_figure(
    fig: plt.Figure,
    path: Path,
    *,
    dpi: int = 300,
    layout: str = "constrained",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if layout == "tight":
        fig.tight_layout()
    elif layout != "none":
        fig.set_constrained_layout(True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", pad_inches=0.04)
    svg_path = path.with_suffix(".svg")
    fig.savefig(svg_path, format="svg", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")
    print(f"wrote {svg_path}")


def _strategy_bench_dirs(root: Path | None = None) -> list[Path]:
    base = root or release_root()
    dirs: list[Path] = []
    for lane in STRATEGY_BENCH_DIRS:
        bench_root = base / "results" / lane / "fit_benchmark"
        if not bench_root.is_dir():
            continue
        for model in PAPER_FIT_MODELS:
            bench_dir = bench_root / model
            if bench_dir.is_dir():
                dirs.append(bench_dir)
    return dirs


def _load_strategy_rows(bench_dirs: Path | list[Path]) -> list[dict]:
    if isinstance(bench_dirs, Path):
        bench_dirs = [bench_dirs]
    rows: list[dict] = []
    for bench_dir in bench_dirs:
        model = bench_dir.name
        for path in sorted(bench_dir.glob("*.json")):
            if path.name == "fit_summary.json":
                continue
            target = path.stem
            for entry in json.loads(path.read_text()):
                rows.append({"target": target, "model": model, **entry})
    if not rows:
        paths = ", ".join(str(d) for d in bench_dirs)
        raise FileNotFoundError(f"no benchmark JSON under {paths}")
    return rows


def _strategy_rows_for_figures(rows: list[dict]) -> list[dict]:
    """Keep only targets in STRATEGY_TARGET_ORDER (heatmap and runtime share this set)."""
    allowed = set(STRATEGY_TARGET_ORDER)
    filtered = [row for row in rows if row["target"] in allowed]
    if not filtered:
        raise ValueError("no strategy-benchmark rows match STRATEGY_TARGET_ORDER")
    return filtered


def _aggregate_strategy_rows(rows: list[dict]) -> list[dict]:
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        model = str(row.get("model", "acm5"))
        by_key[(model, row["strategy"])].append(row)
    agg: list[dict] = []
    for (model, strategy), group in by_key.items():
        agg.append(
            {
                "model": model,
                "strategy": strategy,
                "label": STRATEGY_LABELS.get(strategy, strategy),
                "model_label": MODEL_LABELS.get(model, model),
                "family": STRATEGY_FAMILY.get(strategy, strategy),
                "n_targets": len(group),
                "mean_weighted_error": statistics.mean(r["weighted_error"] for r in group),
                "mean_fit_wall_s": statistics.mean(r["fit_wall_s"] for r in group),
            }
        )
    return sorted(agg, key=lambda r: (r["model"], r["mean_weighted_error"]))


def _strategy_order_from_agg(agg: list[dict]) -> list[str]:
    """Stable strategy column order from mean error across models (prefer ACM-5)."""
    preferred = [row for row in agg if row["model"] == "acm5"]
    source = preferred if preferred else agg
    seen: list[str] = []
    for row in sorted(source, key=lambda r: r["mean_weighted_error"]):
        if row["strategy"] not in seen:
            seen.append(row["strategy"])
    for row in agg:
        if row["strategy"] not in seen:
            seen.append(row["strategy"])
    return seen


def plot_strategy_mean_error(agg: list[dict], out: Path) -> None:
    ensure_rcparams()
    # Prefer ACM-5 panel when multi-model; fall back to first model.
    models = sorted({row["model"] for row in agg}, key=lambda m: PAPER_FIT_MODELS.index(m) if m in PAPER_FIT_MODELS else 99)
    model = "acm5" if "acm5" in models else models[0]
    subset = [row for row in agg if row["model"] == model]
    labels = [row["label"] for row in subset]
    values = [row["mean_weighted_error"] for row in subset]
    y_pos = np.arange(len(labels))

    fig_h = max(FIGSIZE_COLUMN_BAR[1], 0.34 * len(labels) + 1.2)
    fig, ax = plt.subplots(figsize=(FIGSIZE_COLUMN_BAR[0], fig_h))
    ax.barh(
        y_pos,
        values,
        color=BAR_COLOR,
        edgecolor=BAR_EDGE_COLOR,
        linewidth=BAR_EDGE_WIDTH,
        height=0.72,
    )
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=TICK_SIZE)
    ax.invert_yaxis()
    set_axis_labels(
        ax,
        title=f"Mean weighted DC error by search strategy ({MODEL_LABELS.get(model, model)})",
        xlabel="Mean weighted error",
    )
    apply_style(ax, grid_axis="x")
    _write_figure(fig, out)


def plot_strategy_heatmap(rows: list[dict], agg: list[dict], out: Path) -> None:
    from matplotlib.colors import LogNorm

    ensure_rcparams()
    strategy_order = _strategy_order_from_agg(agg)
    targets = list(STRATEGY_TARGET_ORDER)
    models = [
        m
        for m in PAPER_FIT_MODELS
        if any(row.get("model") == m for row in rows)
    ]
    if not models:
        models = sorted({str(row.get("model", "acm5")) for row in rows})

    n_models = len(models)
    fig_w = FIGSIZE_COLUMN_HEATMAP[0]
    panel_h = max(1.35, 0.18 * len(targets) + 0.55)
    fig_h = panel_h * n_models + 0.85
    fig = plt.figure(figsize=(fig_w, fig_h))
    gs = fig.add_gridspec(
        n_models,
        2,
        width_ratios=[24, 1],
        height_ratios=[1] * n_models,
        wspace=0.06,
        hspace=0.22,
        left=0.18,
        right=0.98,
        top=0.96,
        bottom=0.10,
    )

    all_vals = np.array(
        [float(r["weighted_error"]) for r in rows if r["target"] in targets],
        dtype=float,
    )
    if all_vals.size == 0:
        raise ValueError("no strategy-benchmark data for heatmap")
    norm = LogNorm(
        vmin=max(float(all_vals.min()) * 0.9, 1e-3),
        vmax=float(all_vals.max()) * 1.05,
    )
    cmap = plt.matplotlib.colors.LinearSegmentedColormap.from_list(
        "devplot_blue",
        ["#f5f8ff", BAR_COLOR],
    )
    cmap.set_bad(color="#e6e6e6")

    im = None
    for mi, model in enumerate(models):
        matrix = np.full((len(targets), len(strategy_order)), np.nan)
        for i, target in enumerate(targets):
            for j, strategy in enumerate(strategy_order):
                for row in rows:
                    if (
                        row.get("model") == model
                        and row["target"] == target
                        and row["strategy"] == strategy
                    ):
                        matrix[i, j] = row["weighted_error"]
                        break
        ax = fig.add_subplot(gs[mi, 0])
        masked = np.ma.masked_invalid(matrix)
        im = ax.imshow(masked, aspect="auto", cmap=cmap, norm=norm)
        for i in range(len(targets)):
            for j in range(len(strategy_order)):
                if np.isnan(matrix[i, j]):
                    ax.add_patch(
                        plt.Rectangle(
                            (j - 0.5, i - 0.5),
                            1,
                            1,
                            facecolor="#e6e6e6",
                            edgecolor="white",
                            linewidth=0.6,
                            hatch="///",
                            zorder=2,
                        )
                    )
        ax.set_yticks(np.arange(len(targets)))
        ax.set_yticklabels(
            [STRATEGY_TARGET_LABELS.get(t, t) for t in targets],
            fontsize=max(TICK_SIZE - 1, 7),
        )
        if mi == n_models - 1:
            ax.set_xticks(np.arange(len(strategy_order)))
            ax.set_xticklabels(
                [STRATEGY_LABELS[s] for s in strategy_order],
                rotation=40,
                ha="right",
                fontsize=max(TICK_SIZE - 1, 7),
            )
        else:
            ax.set_xticks([])
        title = MODEL_LABELS.get(model, model)
        if n_models == 1:
            title = "Weighted DC error: fit target × search strategy"
        set_axis_labels(
            ax,
            title=title,
            xlabel="Search strategy" if mi == n_models - 1 else None,
            ylabel="Fit target" if mi == n_models // 2 else None,
        )
        apply_style(ax, grid_axis=None)
        ax.grid(False)

    cax = fig.add_subplot(gs[0, 1])
    cbar = fig.colorbar(im, cax=cax)
    cbar.set_label("Weighted error", fontsize=CBAR_LABEL_SIZE)
    cbar.ax.tick_params(labelsize=TICK_SIZE)
    for mi in range(1, n_models):
        fig.add_subplot(gs[mi, 1]).axis("off")
    _write_figure(fig, out, layout="none")


def _runtime_time_axis(xmax_raw: float) -> tuple[float, list[int]]:
    """Pick a readable wall-time axis for the runtime scatter (narrow column figure)."""
    padded = xmax_raw * 1.08
    if padded <= 900:
        step = 200
    elif padded <= 1800:
        step = 500
    else:
        step = 1000
    xmax = int(math.ceil(padded / step) * step)
    ticks = list(range(0, xmax + 1, step))
    return float(xmax), ticks


def plot_strategy_runtime_tradeoff(agg: list[dict], out: Path) -> None:
    from matplotlib.lines import Line2D

    ensure_rcparams()
    fig, ax = plt.subplots(figsize=FIGSIZE_COLUMN_RUNTIME)
    models = [
        m
        for m in PAPER_FIT_MODELS
        if any(row.get("model") == m for row in agg)
    ]
    if not models:
        models = sorted({str(row.get("model", "acm5")) for row in agg})

    xmax_raw = max(float(row["mean_fit_wall_s"]) for row in agg)
    xmax, xticks = _runtime_time_axis(xmax_raw)
    ymax = max(row["mean_weighted_error"] for row in agg) * 1.08

    for model in models:
        for row in agg:
            if row.get("model") != model:
                continue
            ax.scatter(
                row["mean_fit_wall_s"],
                row["mean_weighted_error"],
                s=SCATTER_SIZE_LARGE * 0.55,
                color=STRATEGY_FAMILY_COLORS.get(row["family"], COLOR_REFERENCE),
                marker=MODEL_MARKERS.get(model, "o"),
                edgecolors="white",
                linewidths=0.8,
                zorder=3,
            )

    model_handles = [
        Line2D(
            [0],
            [0],
            marker=MODEL_MARKERS[m],
            color="none",
            markerfacecolor=COLOR_REFERENCE,
            markeredgecolor=COLOR_REFERENCE,
            markersize=7,
            label=MODEL_LABELS.get(m, m),
        )
        for m in models
    ]
    family_handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor=STRATEGY_FAMILY_COLORS[fam],
            markeredgecolor="white",
            markersize=7,
            label=fam,
        )
        for fam in STRATEGY_FAMILY_COLORS
        if any(row["family"] == fam for row in agg)
    ]
    ax.legend(
        handles=model_handles + family_handles,
        fontsize=LEGEND_SIZE - 1,
        loc="upper right",
        framealpha=0.92,
        markerscale=0.9,
        borderpad=0.4,
        labelspacing=0.35,
    )

    annotate_rows = [row for row in agg if row.get("model") == "acm5"]
    if not annotate_rows:
        annotate_rows = agg
    for row in annotate_rows:
        dx, dy, ha, va = _runtime_annotation_offset(row)
        ax.annotate(
            row["label"],
            (row["mean_fit_wall_s"], row["mean_weighted_error"]),
            textcoords="offset points",
            xytext=(dx, dy),
            fontsize=ANNOT_SIZE - 1,
            color=COLOR_REFERENCE,
            ha=ha,
            va=va,
            clip_on=False,
        )

    ax.set_xlim(0, xmax)
    ax.set_xticks(xticks)
    ax.set_ylim(0, ymax)
    set_axis_labels(
        ax,
        title="Accuracy vs. wall time",
        xlabel="Mean wall time (s)",
        ylabel="Mean weighted error",
    )
    apply_style(ax)
    fig.subplots_adjust(left=0.14, right=0.98, top=0.90, bottom=0.15)
    _write_figure(fig, out, layout="none")


def plot_strategy_benchmark(bench_dirs: Path | list[Path], out_dir: Path) -> None:
    rows = _strategy_rows_for_figures(_load_strategy_rows(bench_dirs))
    agg = _aggregate_strategy_rows(rows)
    plot_strategy_heatmap(rows, agg, out_dir / "fig_strategy_heatmap.png")
    plot_strategy_runtime_tradeoff(agg, out_dir / "fig_strategy_runtime.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commercial-dir",
        type=Path,
        default=release_root() / "results" / "commercial",
    )
    parser.add_argument(
        "--ptm-dir",
        type=Path,
        default=release_root() / "results" / "ptm",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=release_root() / "figures",
    )
    parser.add_argument(
        "--strategy-bench-dir",
        type=Path,
        default=None,
        help="Path to results/<lane>/fit_benchmark/acm5 for strategy stress-test figures",
    )
    parser.add_argument(
        "--strategy-bench-only",
        action="store_true",
        help="Generate only strategy benchmark figures (skip commercial/PTM plots)",
    )
    args = parser.parse_args()

    out = args.out_dir
    if args.strategy_bench_only:
        bench_dirs = (
            [args.strategy_bench_dir]
            if args.strategy_bench_dir is not None
            else _strategy_bench_dirs()
        )
        plot_strategy_benchmark(bench_dirs, out)
        return

    plot_overview_diagram(out / "fig_overview.png")
    plot_pipeline_diagram(out / "fig_pipeline.png")
    plot_ptm_params(args.ptm_dir, out / "fig_ptm_params.png")
    plot_idvg_sky130_corners(args.commercial_dir, "1p8", out / "fig_idvg_sky130_tt.png")


if __name__ == "__main__":
    main()
