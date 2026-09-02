"""Matplotlib style for acm-fit benchmark plots (dev-plot palette).

Synced with the dev-plot skill: bold sans-serif, visible top/right spines,
MATLAB-aligned blue/red/purple series colors.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

FIGSIZE = (11, 5)
FIGSIZE_STANDARD = (7.5, 4.5)
FIGSIZE_COMBINED = (8.5, 5.0)
FIGSIZE_IDVG_ROW = (10.0, 3.2)

BAR_COLOR = "#0033cc"
BAR_EDGE_COLOR = "#002080"
COLOR_PRIMARY = "#0033cc"
COLOR_SECONDARY = "#cc0000"
COLOR_ACCENT = "#7f3fbf"
COLOR_REFERENCE = "#555555"
COLOR_TRIAL = "#7f7f7f"

LINE_COLORS = {
    "energy": COLOR_PRIMARY,
    "dnl": COLOR_PRIMARY,
    "inl": COLOR_SECONDARY,
    "sndr": COLOR_PRIMARY,
    "sfdr": COLOR_SECONDARY,
    "thd": COLOR_ACCENT,
    "enob": "#e67300",
}
MULTI_SERIES_COLORS = (COLOR_PRIMARY, COLOR_SECONDARY, COLOR_ACCENT)
PURPLE_CYCLE = ("#7f3fbf", "#9b59b6", "#6a1b9a", "#4a148c")

LINEWIDTH_MAIN = 4.0
LINEWIDTH_SECONDARY = 3.0
GRID_ALPHA = 0.35
TITLE_SIZE = 17
LABEL_SIZE = 13
TICK_SIZE = 10
LEGEND_SIZE = 9
BAR_EDGE_WIDTH = 1.0
SPINE_WIDTH = 2.0
GRID_LINEWIDTH = 1.1

_SAVE_DPI = 150

_rc_applied = False


def ensure_rcparams() -> None:
    """Apply global typography once per process."""
    global _rc_applied
    if _rc_applied:
        return
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Arial", "Liberation Sans", "DejaVu Sans"]
    plt.rcParams["font.weight"] = "bold"
    plt.rcParams["axes.labelweight"] = "bold"
    plt.rcParams["axes.titleweight"] = "bold"
    _rc_applied = True


def apply_style(ax: plt.Axes, *, grid_axis: str | None = None) -> None:
    """Apply consistent axis styling."""
    if grid_axis is None:
        ax.grid(alpha=GRID_ALPHA, linewidth=GRID_LINEWIDTH)
    else:
        ax.grid(axis=grid_axis, alpha=GRID_ALPHA, linewidth=GRID_LINEWIDTH)
    ax.tick_params(axis="both", labelsize=TICK_SIZE)
    for spine in ax.spines.values():
        spine.set_linewidth(SPINE_WIDTH)
    ax.spines["top"].set_visible(True)
    ax.spines["right"].set_visible(True)


def series_color(index: int) -> str:
    """Cycle dev-plot multi-series colors (no tab10)."""
    return MULTI_SERIES_COLORS[index % len(MULTI_SERIES_COLORS)]


def set_axis_labels(
    ax: plt.Axes,
    *,
    title: str | None = None,
    xlabel: str | None = None,
    ylabel: str | None = None,
) -> None:
    if title is not None:
        ax.set_title(title, fontsize=TITLE_SIZE)
    if xlabel is not None:
        ax.set_xlabel(xlabel, fontsize=LABEL_SIZE)
    if ylabel is not None:
        ax.set_ylabel(ylabel, fontsize=LABEL_SIZE)


def save_figure(fig: plt.Figure, path: Path, *, dpi: int = _SAVE_DPI) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


__all__ = [
    "FIGSIZE",
    "FIGSIZE_COMBINED",
    "FIGSIZE_IDVG_ROW",
    "FIGSIZE_STANDARD",
    "COLOR_PRIMARY",
    "COLOR_REFERENCE",
    "COLOR_SECONDARY",
    "COLOR_TRIAL",
    "LINEWIDTH_MAIN",
    "LINEWIDTH_SECONDARY",
    "LEGEND_SIZE",
    "MULTI_SERIES_COLORS",
    "SPINE_WIDTH",
    "TITLE_SIZE",
    "apply_style",
    "ensure_rcparams",
    "save_figure",
    "series_color",
    "set_axis_labels",
]
