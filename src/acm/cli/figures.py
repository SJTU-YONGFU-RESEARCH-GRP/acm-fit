#!/usr/bin/env python3
"""Generate LASCAS paper figures from acm-fit benchmark results."""

from __future__ import annotations

from acm.cli._root import release_root

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from acm.plot_style import (
    COLOR_ACCENT,
    COLOR_PRIMARY,
    COLOR_REFERENCE,
    COLOR_SECONDARY,
    FIGSIZE,
    LEGEND_SIZE,
    LINEWIDTH_MAIN,
    LINEWIDTH_SECONDARY,
    SPINE_WIDTH,
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

CORNER_DISPLAY = {
    "tt": "TT",
    "typical": "Typ.",
    "ss": "SS",
    "ff": "FF",
}


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

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(
        xs,
        ys,
        "o-",
        color=COLOR_PRIMARY,
        linewidth=LINEWIDTH_MAIN,
        markersize=8,
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
    save_figure(fig, out, dpi=200)
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

    fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharex=False)
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

    for ax, param in zip(axes.flat, CORNER_PARAMS):
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
                markersize=7,
                color=series_color(base_idx),
                label=base_pdk,
            )
        set_axis_labels(
            ax,
            title=param_labels[param],
            xlabel="Process corner",
            ylabel=param_labels[param],
        )
        apply_style(ax)
    axes[0, 0].legend(fontsize=LEGEND_SIZE)
    fig.suptitle(
        "Extracted DC parameters across process corners",
        fontsize=TITLE_SIZE,
        fontweight="bold",
    )
    save_figure(fig, out, dpi=200)
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
    fig, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=FIGSIZE)
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
    ax_log.legend(fontsize=LEGEND_SIZE)
    ax_lin.legend(fontsize=LEGEND_SIZE)

    save_figure(fig, out, dpi=200)
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
    save_figure(fig, out, dpi=200)
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
    save_figure(fig, out, dpi=200)
    print(f"wrote {out}")


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
    args = parser.parse_args()

    out = args.out_dir
    plot_overview_diagram(out / "fig_overview.png")
    plot_pipeline_diagram(out / "fig_pipeline.png")
    plot_ptm_scaling(args.ptm_dir, out / "fig_ptm_scaling.png")
    plot_corner_params(args.commercial_dir, out / "fig_corner_params.png")
    plot_idvg_overlay(args.commercial_dir, "sky130_tt", "1p8", out / "fig_idvg_sky130_tt.png")


if __name__ == "__main__":
    main()
