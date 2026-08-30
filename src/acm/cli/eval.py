#!/usr/bin/env python3
"""Run the multi-analysis ACM evaluation suite (DC/AC/noise/transient/temp)."""

from __future__ import annotations

from acm.cli._root import release_root

import argparse
import sys
from pathlib import Path

from acm.eval import run_eval_suite  # noqa: E402
from acm.eval.config import SUPPORTED_ANALYSES, SUPPORTED_SIMULATORS  # noqa: E402
from acm.report import write_regression_reports  # noqa: E402


def _csv_list(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated CLI list."""
    items = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not items:
        raise ValueError("expected a non-empty comma-separated list")
    return items


def main() -> None:
    """Parse CLI arguments and execute the evaluation suite."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=release_root() / "config/eval_suite.json",
        help="Eval suite policy JSON.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=release_root() / "results",
        help="Results root (writes results/<model>/eval/...).",
    )
    parser.add_argument(
        "--openvaf-binary",
        type=Path,
        default=release_root() / "work/openvaf-r",
        help="OpenVAF binary for ngspice OSDI compile.",
    )
    parser.add_argument(
        "--models",
        type=str,
        default="acm5",
        help="Comma-separated model names (acm4,acm5,...).",
    )
    parser.add_argument(
        "--pdks",
        type=str,
        default="sky130,gf180mcu",
        help="Comma-separated PDK names.",
    )
    parser.add_argument(
        "--analyses",
        type=str,
        default=",".join(SUPPORTED_ANALYSES),
        help=f"Comma-separated analyses ({','.join(SUPPORTED_ANALYSES)}).",
    )
    parser.add_argument(
        "--simulators",
        type=str,
        default="ngspice,spectre,hspice",
        help=f"Comma-separated simulators ({','.join(SUPPORTED_SIMULATORS)}).",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=4,
        help="Parallel worker threads.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore cache and re-run all jobs.",
    )
    args = parser.parse_args()

    outputs = run_eval_suite(
        repo_root=release_root(),
        config_path=args.config,
        results_dir=args.results_dir,
        openvaf_binary=args.openvaf_binary,
        models=_csv_list(args.models),
        pdks=_csv_list(args.pdks),
        analyses=_csv_list(args.analyses),
        simulators=_csv_list(args.simulators),
        jobs=args.jobs,
        force=args.force,
    )
    for model, path in sorted(outputs.items()):
        print(f"eval {model}: {path}")
    reports = write_regression_reports(repo_root=release_root(), results_dir=args.results_dir)
    print(f"SUMMARY: {reports['summary']}")


if __name__ == "__main__":
    main()
