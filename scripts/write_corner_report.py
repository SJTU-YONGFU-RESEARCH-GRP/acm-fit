#!/usr/bin/env python3
"""Write CORNER_REPORT.md from fitted parameter cards."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from acm_report import write_corner_report  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=ROOT / "results",
    )
    parser.add_argument("--model", type=str, default="acm5")
    args = parser.parse_args()
    path = write_corner_report(results_dir=args.results_dir, model=args.model)
    print(path)


if __name__ == "__main__":
    main()
