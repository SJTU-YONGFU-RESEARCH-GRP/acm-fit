#!/usr/bin/env python3
"""Golden I-V → ACM fit → multi-sim predict benches (prior-art ACM flow).

Layout::

    results/SUMMARY.md
    results/golden/<pdk>/
    results/<model>/REPORT.md
    results/<model>/fit/<pdk>.json
    results/<model>/benches/<pdk>/<sim>/<analysis>/
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from acm_eval.config import load_suite_config  # noqa: E402
from acm_eval.suite import capture_golden_refs  # noqa: E402
from acm_golden import capture_golden_iv, load_golden_config, load_golden_device  # noqa: E402
from acm_opt.fit_golden import (  # noqa: E402
    FitResult,
    fit_model_to_golden,
    write_combined_error_vs_iteration_plot,
    write_error_vs_iteration_plot,
    write_fit_history_csv,
    write_fitted_card,
)
from acm_opt.loss import loss_policy_from_mapping  # noqa: E402
from acm_opt.models import resolve_models  # noqa: E402
from acm_opt.predict import run_predict_benches  # noqa: E402
from acm_report import write_corner_report, write_regression_reports  # noqa: E402


def _compile_osdi(va: Path, osdi: Path, openvaf: Path) -> None:
    """Compile Verilog-A if OSDI missing or stale."""
    if osdi.is_file() and osdi.stat().st_mtime >= va.stat().st_mtime:
        return
    proc = subprocess.run(
        [str(openvaf), str(va)],
        cwd=str(va.parent),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not osdi.is_file():
        raise RuntimeError(f"OpenVAF failed for {va}:\n{proc.stdout}\n{proc.stderr}")


def _model_dir(results_dir: Path, model_name: str) -> Path:
    """Return ``results/<model>/``."""
    path = results_dir / model_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def main() -> None:
    """Run golden → fit → predict pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config/golden_suite.json",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=ROOT / "results",
    )
    parser.add_argument(
        "--openvaf-binary",
        type=Path,
        default=ROOT / "work/openvaf-r",
    )
    parser.add_argument("--skip-golden", action="store_true")
    parser.add_argument("--skip-fit", action="store_true")
    parser.add_argument("--skip-predict", action="store_true")
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument(
        "--simulators",
        type=str,
        default=None,
        help="Override predict simulators (comma list).",
    )
    args = parser.parse_args()

    results_dir = args.results_dir
    golden_dir = results_dir / "golden"
    cfg = load_golden_config(args.config, ROOT)
    targets = cfg["_targets"]
    models = resolve_models(ROOT, tuple(cfg["fit_models"]))
    policy = loss_policy_from_mapping(cfg["fit_loss"])
    if args.iterations is not None:
        policy = loss_policy_from_mapping(
            {**policy.to_dict(), "optuna_trials": int(args.iterations)}
        )
    analysis_defaults = cfg.get("analysis_defaults", {})
    analyses = tuple(cfg["predict_analyses"])
    sims = tuple(
        s.strip()
        for s in (args.simulators or ",".join(cfg["predict_simulators"])).split(",")
        if s.strip()
    )

    compiled: set[Path] = set()
    for model in models:
        if model.va_path in compiled:
            continue
        _compile_osdi(model.va_path, model.osdi_path, args.openvaf_binary)
        compiled.add(model.va_path)

    if not args.skip_golden:
        print("=== Step 1: build golden I-V from PDK BSIM ===")
        for name, target in targets.items():
            device_dir = golden_dir / name
            print(f"  capturing {name} ...")
            capture_golden_iv(
                target=target,
                output_dir=device_dir,
                vg_start=float(cfg["vg_start"]),
                vg_step=float(cfg["vg_step"]),
                vds_fractions=[float(x) for x in cfg["vds_fractions"]],
            )
            print(f"  wrote {device_dir}")

    if policy.weight_ac > 0.0 or policy.weight_noise > 0.0:
        print("=== Step 1b: capture eval golden AC/noise refs for multi-obj fit ===")
        eval_suite = load_suite_config(ROOT / "config/eval_suite.json", ROOT)
        needed = []
        if policy.weight_ac > 0.0:
            needed.append("ac")
        if policy.weight_noise > 0.0:
            needed.append("noise")
        capture_golden_refs(
            suite=eval_suite,
            results_dir=results_dir,
            pdks=tuple(targets),
            analyses=tuple(needed),
            force=False,
        )

    fit_by_model: dict[str, list[FitResult]] = {m.name: [] for m in models}
    if not args.skip_fit:
        print("=== Step 2: fit ACM to golden I-V ===")
        for name in targets:
            golden = load_golden_device(golden_dir / name)
            for model in models:
                model_root = _model_dir(results_dir, model.name)
                fit_dir = model_root / "fit"
                fit_dir.mkdir(parents=True, exist_ok=True)
                work_dir = fit_dir / "_work" / name
                print(f"  fitting {model.name} on {name} ...")
                result = fit_model_to_golden(
                    model=model,
                    golden=golden,
                    work_dir=work_dir,
                    seed=13,
                    vg_start=float(cfg["vg_start"]),
                    vg_step=float(cfg["vg_step"]),
                    policy=policy,
                    refine=True,
                    results_dir=results_dir,
                    analysis_defaults=analysis_defaults,
                )
                card_path = fit_dir / f"{name}.json"
                write_fitted_card(
                    card_path,
                    result,
                    vdd=golden.vdd,
                    extra={
                        k: v
                        for k, v in (
                            ("base_pdk", golden.base_pdk),
                            ("corner", golden.corner),
                        )
                        if v is not None
                    },
                )
                write_fit_history_csv(fit_dir / f"{name}_history.csv", result)
                write_error_vs_iteration_plot(
                    fit_dir / f"{name}_error_vs_iter.png",
                    result,
                )
                fit_by_model[model.name].append(result)
                print(
                    f"    err={result.weighted_error:.4g} "
                    f"wall={result.fit_wall_s:.2f}s -> {card_path}"
                )
                if work_dir.exists():
                    shutil.rmtree(work_dir)

        for model in models:
            results = fit_by_model[model.name]
            if not results:
                continue
            fit_dir = _model_dir(results_dir, model.name) / "fit"
            write_combined_error_vs_iteration_plot(
                fit_dir / "error_vs_iteration.png",
                results,
            )
            fit_rows = [
                {
                    "pdk": r.pdk,
                    "model": r.model,
                    "weighted_error": r.weighted_error,
                    "rmse_linear": r.rmse_linear,
                    "rmse_log": r.rmse_log,
                    "fit_wall_s": r.fit_wall_s,
                    "n_evals": r.n_evals,
                    "peak_rss_kb": r.peak_rss_kb,
                }
                for r in results
            ]
            (fit_dir / "fit_summary.json").write_text(
                json.dumps(fit_rows, indent=2) + "\n"
            )

    if not args.skip_predict:
        print("=== Step 3: predict benches from fitted cards ===")
        model_map = {m.name: m for m in models}
        all_pred: list[dict] = []
        for model in models:
            fit_dir = results_dir / model.name / "fit"
            card_files = sorted(fit_dir.glob("*.json"))
            card_files = [p for p in card_files if p.name != "fit_summary.json"]
            if not card_files:
                raise FileNotFoundError(f"no fitted cards in {fit_dir}")
            benches_dir = _model_dir(results_dir, model.name) / "benches"
            model_rows: list[dict] = []
            for card_path in card_files:
                card = json.loads(card_path.read_text())
                pdk = str(card["pdk"])
                out = benches_dir / pdk
                print(f"  predict {model.name}/{pdk} on {sims} ...")
                rows = run_predict_benches(
                    model=model_map[model.name],
                    card=card,
                    output_dir=out,
                    analyses=analyses,
                    simulators=sims,
                    jobs=args.jobs,
                )
                model_rows.extend(rows)
                all_pred.extend(rows)
            (benches_dir / "summary.json").write_text(
                json.dumps(model_rows, indent=2) + "\n"
            )
        n_fail = sum(1 for row in all_pred if not row["ok"])
        print(f"  predict jobs={len(all_pred)} failed={n_fail}")
        if n_fail:
            raise SystemExit(1)

    print("=== Step 4: write SUMMARY.md + per-model REPORT.md ===")
    reports = write_regression_reports(repo_root=ROOT, results_dir=results_dir)
    print(f"  {reports['summary']}")
    for model, path in sorted(reports.items()):
        if model == "summary":
            continue
        print(f"  {path}")

    for model in models:
        fit_dir = results_dir / model.name / "fit"
        if not fit_dir.is_dir():
            continue
        try:
            corner_path = write_corner_report(
                results_dir=results_dir,
                model=model.name,
            )
            print(f"  {corner_path}")
        except (FileNotFoundError, ValueError):
            pass

    print("Pipeline complete.")
    print(f"  results: {results_dir}")
    print(f"  summary: {results_dir / 'SUMMARY.md'}")


if __name__ == "__main__":
    main()
