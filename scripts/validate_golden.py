#!/usr/bin/env python3
"""Validate user-supplied golden I-V directories (meta.json + CSV layout)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from acm_golden import validate_golden_device  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Device dirs (each must contain meta.json and idvg_vds_*.csv).",
    )
    args = parser.parse_args()

    ok = 0
    for path in args.paths:
        device_dir = path.resolve()
        try:
            dev = validate_golden_device(device_dir)
        except (FileNotFoundError, ValueError, OSError) as exc:
            print(f"FAIL {device_dir}: {exc}")
            continue
        n_pts = sum(len(c.vg) for c in dev.curves)
        print(
            f"OK   {device_dir.name}: pdk={dev.pdk} vdd={dev.vdd} "
            f"curves={len(dev.curves)} points={n_pts}"
        )
        ok += 1

    if ok != len(args.paths):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
