#!/usr/bin/env python3
"""Build committed custom-lane robustness examples from frozen golden corpora."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from acm.cli._root import release_root
from acm.golden import load_golden_device, validate_golden_device


def _vds_tag(vds: float) -> str:
    return f"idvg_vds_{vds:.4g}".replace(".", "p")


def _write_curve(path: Path, vg: np.ndarray, id_ref: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["vg", "id_ref"])
        for v, i in zip(vg, id_ref):
            writer.writerow([v, i])


def _export_subset(
    *,
    src_dir: Path,
    out_dir: Path,
    target_name: str,
    vds_keep: list[float],
    source_label: str,
    role: str,
    vg_stride: int = 1,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    dev = load_golden_device(src_dir)
    kept = [c for c in dev.curves if any(abs(c.vds - v) < 1e-9 for v in vds_keep)]
    if len(kept) != len(vds_keep):
        have = [c.vds for c in dev.curves]
        raise ValueError(
            f"{src_dir}: requested vds {vds_keep}, available {have}"
        )

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    vds_list = [float(c.vds) for c in kept]
    for curve in kept:
        vg = curve.vg[::vg_stride]
        id_ref = curve.id_ref[::vg_stride]
        _write_curve(out_dir / f"{_vds_tag(curve.vds)}.csv", vg, id_ref)

    meta = {
        "pdk": target_name,
        "vdd": dev.vdd,
        "width_m": dev.width_m,
        "length_m": dev.length_m,
        "polarity": dev.meta.get("polarity", "nmos"),
        "vg_start": float(dev.meta.get("vg_start", float(kept[0].vg[0]))),
        "vg_step": float(dev.meta.get("vg_step", 0.05)) * vg_stride,
        "vds_list": vds_list,
        "n_points_per_curve": len(kept[0].vg[::vg_stride]),
        "source": source_label,
        "role": role,
    }
    if dev.base_pdk is not None:
        meta["base_pdk"] = dev.base_pdk
    if dev.corner is not None:
        meta["corner"] = dev.corner
    if extra_meta:
        meta.update(extra_meta)
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    validate_golden_device(out_dir)


def build_all(examples_root: Path, golden_root: Path) -> list[str]:
    """Regenerate every example under ``data/examples/``."""
    specs: list[dict[str, Any]] = [
        {
            "name": "custom_1vds_sat",
            "src": golden_root / "ptm/ptm180",
            "vds_keep": [1.8],
            "source": "robustness_1vds_saturation",
            "note": "Single high-Vds Id-Vg (hardest minimal set)",
        },
        {
            "name": "custom_2vds",
            "src": golden_root / "ptm/ptm180",
            "vds_keep": [0.09, 1.8],
            "source": "robustness_2vds_low_high",
            "note": "Two sweeps: subthreshold bias + saturation",
        },
        {
            "name": "custom_3vds_std",
            "src": golden_root / "ptm/ptm180",
            "vds_keep": [0.09, 0.9, 1.8],
            "source": "robustness_3vds_standard",
            "note": "Recommended default (low / mid / high Vds)",
        },
        {
            "name": "custom_sparse_vg",
            "src": golden_root / "ptm/ptm180",
            "vds_keep": [0.09, 0.9, 1.8],
            "source": "robustness_sparse_vg_sampling",
            "vg_stride": 4,
            "note": "Three Vds with coarse Vg grid (every 4th point)",
        },
        {
            "name": "custom_ptm22",
            "src": golden_root / "ptm/ptm22",
            "vds_keep": [0.0475, 0.475, 0.95],
            "source": "robustness_ptm22_short_channel",
            "note": "22 nm node, 0.95 V supply",
        },
        {
            "name": "custom_sky130_ss",
            "src": golden_root / "commercial/sky130_ss",
            "vds_keep": [0.09, 0.9, 1.8],
            "source": "robustness_sky130_slow_corner",
            "note": "Foundry slow corner (sky130 ss)",
        },
        {
            "name": "custom_sky130_ff",
            "src": golden_root / "commercial/sky130_ff",
            "vds_keep": [0.09, 0.9, 1.8],
            "source": "robustness_sky130_fast_corner",
            "note": "Foundry fast corner (sky130 ff)",
        },
        {
            "name": "custom_gf180_typ",
            "src": golden_root / "commercial/gf180mcu_typical",
            "vds_keep": [0.165, 1.65, 3.3],
            "source": "robustness_gf180_typical",
            "note": "GF180MCU typical, 3.3 V domain",
        },
    ]

    built: list[str] = []
    for spec in specs:
        name = str(spec["name"])
        _export_subset(
            src_dir=Path(spec["src"]),
            out_dir=examples_root / name,
            target_name=name,
            vds_keep=[float(v) for v in spec["vds_keep"]],
            source_label=str(spec["source"]),
            role="golden_iv_for_acm_dc_fit",
            vg_stride=int(spec.get("vg_stride", 1)),
            extra_meta={"robustness_note": spec["note"]},
        )
        built.append(name)

    suite_path = release_root() / "config/golden_suite_custom.example.json"
    _write_suite_config(suite_path, examples_root, built)
    return built


def _write_suite_config(path: Path, examples_root: Path, names: list[str]) -> None:
    targets: dict[str, Any] = {}
    for name in names:
        meta = json.loads((examples_root / name / "meta.json").read_text())
        targets[name] = {
            "data_only": True,
            "vdd": meta["vdd"],
            "width_m": meta["width_m"],
            "length_m": meta["length_m"],
            "polarity": meta.get("polarity", "nmos"),
        }

    payload = {
        "suite_version": 3,
        "description": (
            "Robustness suite: fit ACM-5 from user-style Id-Vg CSVs "
            "(1/2/3 Vds, sparse Vg, corners, nodes)."
        ),
        "vg_start": 0.0,
        "vg_step": 0.05,
        "vds_fractions": [0.05, 0.5, 1.0],
        "fit_models": ["acm5"],
        "predict_analyses": ["dc", "ac", "noise", "transient", "temp"],
        "predict_simulators": ["ngspice"],
        "fit_loss": {
            "id_mode": "absolute",
            "weight_linear": 0.4,
            "weight_log": 0.6,
            "huber_delta": 1.0e-4,
            "region_vt_width_v": 0.0,
            "region_vt_boost": 2.0,
            "weight_dc": 1.0,
            "weight_ac": 0.0,
            "weight_noise": 0.0,
            "weight_temp": 0.0,
            "optuna_trials": 1000,
            "refine_starts": 3,
            "refine_maxiter": 15,
        },
        "analysis_defaults": {
            "ac": {
                "vgs": 0.9,
                "f_start": 1.0e3,
                "f_stop": 1.0e9,
                "points_per_decade": 10,
                "rd_ohm": 1000.0,
            },
            "noise": {
                "vgs": 0.9,
                "f_start": 1.0e3,
                "f_stop": 1.0e9,
                "points_per_decade": 10,
                "rd_ohm": 1000.0,
            },
        },
        "targets": targets,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--examples-dir",
        type=Path,
        default=release_root() / "data/examples",
    )
    parser.add_argument(
        "--golden-dir",
        type=Path,
        default=release_root() / "data/golden",
    )
    parser.add_argument(
        "--suite-out",
        type=Path,
        default=release_root() / "config/golden_suite_custom.example.json",
    )
    args = parser.parse_args()

    names = build_all(args.examples_dir.resolve(), args.golden_dir.resolve())
    print(f"Built {len(names)} examples under {args.examples_dir}")
    for name in names:
        print(f"  {name}")
    print(f"Updated {args.suite_out}")


if __name__ == "__main__":
    main()
