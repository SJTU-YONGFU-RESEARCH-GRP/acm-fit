#!/usr/bin/env python3
"""Write results/SUMMARY.md and results/<model>/REPORT.md from artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from acm_report import write_regression_reports  # noqa: E402


def main() -> None:
    """Regenerate regression markdown reports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    outputs = write_regression_reports(repo_root=ROOT, results_dir=args.results_dir)
    print(f"SUMMARY: {outputs['summary']}")
    for model, path in sorted(outputs.items()):
        if model != "summary":
            print(f"REPORT:  {path}")


if __name__ == "__main__":
    main()
