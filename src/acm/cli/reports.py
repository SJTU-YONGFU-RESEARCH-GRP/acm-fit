#!/usr/bin/env python3
"""Write results/SUMMARY.md and results/<model>/REPORT.md from artifacts."""

from __future__ import annotations

from acm.cli._root import release_root

import argparse
import sys
from pathlib import Path

from acm.report import write_regression_reports  # noqa: E402


def main() -> None:
    """Regenerate regression markdown reports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=release_root() / "results")
    args = parser.parse_args()
    outputs = write_regression_reports(repo_root=release_root(), results_dir=args.results_dir)
    print(f"SUMMARY: {outputs['summary']}")
    for model, path in sorted(outputs.items()):
        if model != "summary":
            print(f"REPORT:  {path}")


if __name__ == "__main__":
    main()
