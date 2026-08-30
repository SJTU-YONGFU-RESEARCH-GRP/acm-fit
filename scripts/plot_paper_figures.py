#!/usr/bin/env python3
"""Generate LASCAS paper figures from acm-fit benchmark results."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent

BLUE = "#0033cc"
RED = "#cc0000"
GRAY = "#555555"

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


def _apply_style(ax: plt.Axes) -> None:
    ax.grid(alpha=0.35, linewidth=0.9)
    ax.tick_params(axis="both", labelsize=10)
    for spine in ax.spines.values():
        spine.set_linewidth(1.2)


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
  fit_dir = ptm_dir / "acm5" / "fit"
  cards = {str(c["pdk"]): c for c in _load_fit_cards(fit_dir)}
  xs, ys = [], []
  for pdk, nm in NODE_ORDER:
      if pdk in cards:
          xs.append(nm)
          ys.append(float(cards[pdk]["weighted_error"]))
  if not xs:
      raise FileNotFoundError(f"no PTM fit cards in {fit_dir}")

  fig, ax = plt.subplots(figsize=(7, 4.5))
  ax.plot(xs, ys, "o-", color=BLUE, linewidth=2, markersize=8, label="ACM-5")
  ax.set_xlabel("PTM technology node (nm)")
  ax.set_ylabel("Weighted DC fit error")
  ax.set_title("ACM-5 vs PTM BSIM golden (DC Id–Vg)")
  ax.set_xscale("log")
  ax.invert_xaxis()
  _apply_style(ax)
  ax.legend()
  fig.tight_layout()
  out.parent.mkdir(parents=True, exist_ok=True)
  fig.savefig(out, dpi=200, bbox_inches="tight")
  plt.close(fig)
  print(f"wrote {out}")


def plot_corner_params(commercial_dir: Path, out: Path) -> None:
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
      "VT0": "VT0 (mV)",
      "IS": "IS (nA)",
      "n": "n",
      "zeta": "ζ",
  }
  scales = {
      "VT0": 1e3,
      "IS": 1e9,
      "n": 1.0,
      "zeta": 1.0,
  }

  for ax, param in zip(axes.flat, CORNER_PARAMS):
      for base_pdk in sorted(by_base):
          group = sorted(by_base[base_pdk], key=lambda c: c["corner"])
          corners = [c["corner"] for c in group]
          vals = [float(c["parameters"][param]) * scales[param] for c in group]
          ax.plot(corners, vals, "o-", linewidth=2, markersize=7, label=base_pdk)
      ax.set_ylabel(param_labels[param])
      ax.set_xlabel("Process corner")
      ax.set_title(param)
      _apply_style(ax)
  axes[0, 0].legend(fontsize=9)
  fig.suptitle("ACM-5 DC parameters vs process corner", fontsize=12, fontweight="bold")
  fig.tight_layout()
  out.parent.mkdir(parents=True, exist_ok=True)
  fig.savefig(out, dpi=200, bbox_inches="tight")
  plt.close(fig)
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
  golden_csv = commercial_dir / "golden" / target / f"idvg_vds_{vds_tag}.csv"
  acm_csv = commercial_dir / "acm5" / "benches" / target / "ngspice" / "dc" / "acm.csv"
  if not golden_csv.is_file():
      raise FileNotFoundError(golden_csv)
  if not acm_csv.is_file():
      raise FileNotFoundError(acm_csv)

  vg_g, id_g = _read_golden_curve(golden_csv)
  vg_a, id_a = _read_golden_curve(acm_csv)

  vds_v = float(vds_tag.replace("p", "."))
  fig, (ax_lin, ax_log) = plt.subplots(1, 2, figsize=(11, 4.5))

  ax_lin.plot(vg_g, id_g * 1e6, color=GRAY, linewidth=2, label="BSIM golden")
  ax_lin.plot(vg_a, id_a * 1e6, color=RED, linewidth=2, linestyle="--", label="ACM-5 fit")
  ax_lin.set_xlabel("Vg (V)")
  ax_lin.set_ylabel("Id (µA)")
  ax_lin.set_title(f"{target}, Vds={vds_v:g} V (linear)")
  _apply_style(ax_lin)

  mask_g = id_g > 0
  mask_a = id_a > 0
  ax_log.semilogy(vg_g[mask_g], id_g[mask_g], color=GRAY, linewidth=2, label="BSIM golden")
  ax_log.semilogy(vg_a[mask_a], id_a[mask_a], color=RED, linewidth=2, linestyle="--", label="ACM-5 fit")
  ax_log.set_xlabel("Vg (V)")
  ax_log.set_ylabel("Id (A)")
  ax_log.set_title(f"{target}, Vds={vds_v:g} V (log)")
  _apply_style(ax_log)
  ax_log.legend()

  fig.suptitle("Id–Vg overlay after automated DC extraction", fontsize=12, fontweight="bold")
  fig.tight_layout()
  out.parent.mkdir(parents=True, exist_ok=True)
  fig.savefig(out, dpi=200, bbox_inches="tight")
  plt.close(fig)
  print(f"wrote {out}")


def plot_pipeline_diagram(out: Path) -> None:
    """Block diagram of the acm-fit workflow (Fig. 1)."""
    fig, ax = plt.subplots(figsize=(9, 2.8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)
    ax.axis("off")

    boxes = [
        (0.2, 1.0, "PDK BSIM\n(ngspice)"),
        (1.8, 1.0, "Golden\nId–Vg"),
        (3.4, 1.0, "Optuna\nDC fit"),
        (5.0, 1.0, "Fitted\nACM card"),
        (6.6, 1.8, "Predict\nbenches"),
        (6.6, 0.2, "Eval vs\nBSIM"),
        (8.2, 1.0, "SUMMARY /\nCORNER_REPORT"),
    ]
    for x, y, label in boxes:
        ax.add_patch(
            plt.Rectangle((x, y), 1.3, 0.9, fill=False, linewidth=1.5, edgecolor=BLUE)
        )
        ax.text(x + 0.65, y + 0.45, label, ha="center", va="center", fontsize=9)

    arrows = [
        (1.5, 1.45, 1.8, 1.45),
        (3.1, 1.45, 3.4, 1.45),
        (4.7, 1.45, 5.0, 1.45),
        (6.3, 1.45, 6.6, 1.65),
        (6.3, 1.45, 6.6, 0.55),
        (7.9, 1.65, 8.2, 1.35),
        (7.9, 0.55, 8.2, 1.15),
    ]
    for x0, y0, x1, y1 in arrows:
        ax.annotate(
            "",
            xy=(x1, y1),
            xytext=(x0, y0),
            arrowprops=dict(arrowstyle="->", lw=1.2, color=GRAY),
        )

    ax.set_title("acm-fit end-to-end pipeline", fontsize=11, fontweight="bold")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
      "--commercial-dir",
      type=Path,
      default=ROOT / "results" / "commercial",
  )
  parser.add_argument(
      "--ptm-dir",
      type=Path,
      default=ROOT / "results" / "ptm",
  )
  parser.add_argument(
      "--out-dir",
      type=Path,
      default=ROOT / "figures",
  )
  args = parser.parse_args()

  out = args.out_dir
  plot_pipeline_diagram(out / "fig_pipeline.png")
  plot_ptm_scaling(args.ptm_dir, out / "fig_ptm_scaling.png")
  plot_corner_params(args.commercial_dir, out / "fig_corner_params.png")
  plot_idvg_overlay(args.commercial_dir, "sky130_tt", "1p8", out / "fig_idvg_sky130_tt.png")


if __name__ == "__main__":
  main()
