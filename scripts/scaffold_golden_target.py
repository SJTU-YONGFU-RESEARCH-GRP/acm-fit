#!/usr/bin/env python3
"""Create meta.json for a user golden target directory (add CSVs separately)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _csv_name(vds: float, polarity: str) -> str:
    tag = f"idvg_vds_{vds:.4g}".replace(".", "p")
    if polarity == "pmos":
        tag = f"pmos_{tag}"
    return f"{tag}.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Target directory to create.")
    parser.add_argument("--pdk", type=str, required=True, help="Target id (matches suite JSON key).")
    parser.add_argument("--vdd", type=float, required=True)
    parser.add_argument("--width-m", type=float, required=True)
    parser.add_argument("--length-m", type=float, required=True)
    parser.add_argument(
        "--vds",
        type=str,
        required=True,
        help="Comma-separated |VDS| values in volts (e.g. 0.09,0.9,1.8).",
    )
    parser.add_argument("--polarity", choices=("nmos", "pmos"), default="nmos")
    parser.add_argument("--vg-start", type=float, default=0.0)
    parser.add_argument("--vg-step", type=float, default=0.05)
    parser.add_argument("--base-pdk", type=str, default=None)
    parser.add_argument("--corner", type=str, default=None)
    parser.add_argument("--force", action="store_true", help="Overwrite existing meta.json.")
    args = parser.parse_args()

    vds_list = [float(x.strip()) for x in args.vds.split(",") if x.strip()]
    if not vds_list:
        raise SystemExit("--vds must list at least one voltage")

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "meta.json"
    if meta_path.exists() and not args.force:
        raise SystemExit(f"{meta_path} exists; pass --force to overwrite")

    meta = {
        "pdk": args.pdk,
        "vdd": args.vdd,
        "width_m": args.width_m,
        "length_m": args.length_m,
        "polarity": args.polarity,
        "vg_start": args.vg_start,
        "vg_step": args.vg_step,
        "vds_list": vds_list,
        "n_points_per_curve": None,
        "source": "user_supplied",
        "role": "golden_iv_for_acm_dc_fit",
    }
    if args.base_pdk is not None:
        meta["base_pdk"] = args.base_pdk
    if args.corner is not None:
        meta["corner"] = args.corner

    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    print(f"Wrote {meta_path}")
    print("Add one CSV per VDS with header 'vg,id_ref':")
    for vds in vds_list:
        print(f"  {out / _csv_name(vds, args.polarity)}  (|VDS|={vds} V)")
    print()
    print("Validate:")
    print(f"  PYTHONPATH=src python3 scripts/validate_golden.py {out}")


if __name__ == "__main__":
    main()
