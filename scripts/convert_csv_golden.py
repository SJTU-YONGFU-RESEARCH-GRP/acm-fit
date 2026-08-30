#!/usr/bin/env python3
"""Import generic vg/id CSV files into an acm-fit golden target directory."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _csv_name(vds: float, polarity: str) -> str:
    tag = f"idvg_vds_{vds:.4g}".replace(".", "p")
    if polarity == "pmos":
        tag = f"pmos_{tag}"
    return f"{tag}.csv"


def _read_curve(path: Path) -> tuple[list[float], list[float]]:
    vg: list[float] = []
    id_ref: list[float] = []
    with path.open(newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{path}: empty file")
        cols = [h.strip().lower() for h in header]
        if "vg" in cols and "id_ref" in cols:
            iv, ii = cols.index("vg"), cols.index("id_ref")
        elif len(header) >= 2:
            iv, ii = 0, 1
        else:
            raise ValueError(f"{path}: expected columns vg,id_ref (or two numeric columns)")
        for row in reader:
            if not row or all(not c.strip() for c in row):
                continue
            vg.append(float(row[iv]))
            id_ref.append(float(row[ii]))
    if not vg:
        raise ValueError(f"{path}: no data rows")
    return vg, id_ref


def _write_curve(path: Path, vg: list[float], id_ref: list[float]) -> None:
    with path.open("w", newline="") as fh:
        fh.write("vg,id_ref\n")
        for x, y in zip(vg, id_ref):
            fh.write(f"{x:.10g},{y:.10g}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pdk", type=str, required=True)
    parser.add_argument("--vdd", type=float, required=True)
    parser.add_argument("--width-m", type=float, required=True)
    parser.add_argument("--length-m", type=float, required=True)
    parser.add_argument("--polarity", choices=("nmos", "pmos"), default="nmos")
    parser.add_argument("--vg-start", type=float, default=None)
    parser.add_argument("--vg-step", type=float, default=None)
    parser.add_argument("--base-pdk", type=str, default=None)
    parser.add_argument("--corner", type=str, default=None)
    parser.add_argument(
        "--curve",
        action="append",
        required=True,
        metavar="VDS:CSV",
        help="Absolute |VDS| in volts and source CSV path, e.g. 0.9:measurements/id_vg_0p9.csv",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    curves: list[tuple[float, Path]] = []
    for spec in args.curve:
        if ":" not in spec:
            raise SystemExit(f"invalid --curve {spec!r}; use VDS:path/to.csv")
        vds_s, csv_s = spec.split(":", 1)
        curves.append((float(vds_s), Path(csv_s)))
    curves.sort(key=lambda x: x[0])

    out = args.out.resolve()
    if out.exists() and any(out.iterdir()) and not args.force:
        raise SystemExit(f"{out} is not empty; pass --force to overwrite")
    out.mkdir(parents=True, exist_ok=True)

    vds_list: list[float] = []
    vg_start = args.vg_start
    vg_step = args.vg_step
    for vds, src in curves:
        if not src.is_file():
            raise SystemExit(f"missing curve CSV: {src}")
        vg, id_ref = _read_curve(src)
        if vg_start is None:
            vg_start = vg[0]
        if vg_step is None and len(vg) > 1:
            vg_step = vg[1] - vg[0]
        dst = out / _csv_name(vds, args.polarity)
        _write_curve(dst, vg, id_ref)
        vds_list.append(vds)
        print(f"  {src} -> {dst.name} ({len(vg)} points)")

    meta = {
        "pdk": args.pdk,
        "vdd": args.vdd,
        "width_m": args.width_m,
        "length_m": args.length_m,
        "polarity": args.polarity,
        "vg_start": float(vg_start if vg_start is not None else 0.0),
        "vg_step": float(vg_step if vg_step is not None else 0.05),
        "vds_list": vds_list,
        "n_points_per_curve": len(vg),
        "source": "user_supplied",
        "role": "golden_iv_for_acm_dc_fit",
    }
    if args.base_pdk is not None:
        meta["base_pdk"] = args.base_pdk
    if args.corner is not None:
        meta["corner"] = args.corner

    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote {out / 'meta.json'}")
    print("Validate:")
    print(f"  PYTHONPATH=src python3 scripts/validate_golden.py {out}")


if __name__ == "__main__":
    main()
