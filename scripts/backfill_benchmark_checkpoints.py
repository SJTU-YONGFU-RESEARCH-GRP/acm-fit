#!/usr/bin/env python3
"""Restore per-strategy benchmark_checkpoint.json files from summary JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from acm.opt.benchmark import _checkpoint_path, _save_checkpoint
from acm.opt.fit import FitResult, fit_result_from_fitted_card


def _result_from_row(
    row: dict,
    *,
    pdk: str,
    model_name: str,
    parameters: dict[str, float],
    fit_profile: str | None,
) -> FitResult:
    return FitResult(
        pdk=pdk,
        model=model_name,
        parameters=parameters,
        weighted_error=float(row["weighted_error"]),
        rmse_linear=float(row["weighted_error"]),
        rmse_log=float(row["rmse_log"]),
        fit_wall_s=float(row["fit_wall_s"]),
        n_evals=int(row["n_evals"]),
        peak_rss_kb=0,
        fit_strategy=str(row["strategy"]),
        fit_profile=fit_profile,
    )


def backfill(
    *,
    results_dir: Path,
    model_name: str,
    targets: tuple[str, ...] | None = None,
) -> int:
    bench_dir = results_dir / "fit_benchmark" / model_name
    fit_dir = results_dir / model_name / "fit"
    work_root = fit_dir / "_work"
    written = 0
    for summary_path in sorted(bench_dir.glob("*.json")):
        pdk = summary_path.stem
        if targets is not None and pdk not in targets:
            continue
        rows = json.loads(summary_path.read_text())
        card_path = fit_dir / f"{pdk}.json"
        card_params: dict[str, float] = {}
        fit_profile: str | None = None
        if card_path.is_file():
            card = fit_result_from_fitted_card(card_path)
            card_params = dict(card.parameters)
            fit_profile = card.fit_profile
        work_dir = work_root / pdk
        for row in rows:
            strategy = str(row["strategy"])
            ckpt = _checkpoint_path(work_dir, strategy)
            if ckpt.is_file():
                continue
            params = dict(card_params)
            result = _result_from_row(
                row,
                pdk=pdk,
                model_name=model_name,
                parameters=params,
                fit_profile=fit_profile,
            )
            _save_checkpoint(ckpt, result)
            written += 1
            print(f"wrote {ckpt}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--model", default="acm5")
    parser.add_argument("--targets", nargs="*", default=None)
    args = parser.parse_args()
    n = backfill(
        results_dir=args.results_dir,
        model_name=args.model,
        targets=tuple(args.targets) if args.targets else None,
    )
    print(f"backfilled {n} checkpoint(s)")


if __name__ == "__main__":
    main()
