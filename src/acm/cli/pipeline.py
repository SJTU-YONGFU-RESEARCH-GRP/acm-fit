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

from acm.cli._root import release_root

import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from acm.eval.config import load_suite_config  # noqa: E402
from acm.eval.suite import capture_golden_refs  # noqa: E402
from acm.golden import (  # noqa: E402
    GoldenDevice,
    GoldenTarget,
    capture_golden_iv,
    load_golden_config,
    load_golden_device,
)
from acm.opt.fit import (  # noqa: E402
    FitResult,
    fit_model_to_golden,
    fit_result_from_fitted_card,
    write_combined_error_vs_iteration_plot,
    write_error_vs_iteration_plot,
    write_fit_history_csv,
    write_fitted_card,
    write_idvg_fit_overlay_plot,
)
from acm.opt.engine import (
    FitEnginePolicy,
    fit_engine_from_mapping,
    fit_job_waves,
    resolve_parent_target_name,
)
from acm.opt.benchmark import (
    benchmark_target_complete,
    collect_benchmark_rows,
    write_fit_benchmark_summary,
)
from acm.opt.loss import LossPolicy, loss_policy_from_mapping  # noqa: E402
from acm.opt.models import ModelSpec, resolve_models  # noqa: E402
from acm.opt.predict import run_predict_benches  # noqa: E402
from acm.report import write_corner_report, write_regression_reports  # noqa: E402


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


def _capture_one_golden(
    *,
    name: str,
    target: GoldenTarget,
    golden_dir: Path,
    vg_start: float,
    vg_step: float,
    vds_fractions: list[float],
) -> str:
    device_dir = golden_dir / name
    print(f"  capturing {name} ...")
    capture_golden_iv(
        target=target,
        output_dir=device_dir,
        vg_start=vg_start,
        vg_step=vg_step,
        vds_fractions=vds_fractions,
    )
    print(f"  wrote {device_dir}")
    return name


def _vg_grid_for_golden(
    golden: GoldenDevice,
    *,
    vg_start: float,
    vg_step: float,
) -> tuple[float, float]:
    """Use Id–Vg sweep metadata from the golden corpus when present."""
    if "vg_start" in golden.meta and "vg_step" in golden.meta:
        return float(golden.meta["vg_start"]), float(golden.meta["vg_step"])
    if golden.curves:
        vg = golden.curves[0].vg
        if len(vg) >= 2:
            return float(vg[0]), float(vg[1] - vg[0])
    return vg_start, vg_step


def _warm_start_params(
    *,
    model: ModelSpec,
    name: str,
    golden_dir: Path,
    fit_dir: Path,
    fit_engine: FitEnginePolicy,
) -> dict[str, float] | None:
    """Load parent-corner fitted parameters when warm-start is configured."""
    warm = fit_engine.warm_start
    if warm is None:
        return None
    golden = load_golden_device(golden_dir / name)
    parent_name = resolve_parent_target_name(
        base_pdk=golden.base_pdk,
        corner=golden.corner,
        warm_start=warm,
    )
    if parent_name is None:
        return None
    card_path = fit_dir / f"{parent_name}.json"
    if not card_path.is_file():
        return None
    card = json.loads(card_path.read_text())
    params = card.get("parameters")
    if not isinstance(params, dict):
        raise ValueError(f"invalid fitted card (no parameters): {card_path}")
    return {
        name: float(params[name])
        for name in model.free_params
        if name in params
    }


def _fit_one_target(
    *,
    model: ModelSpec,
    name: str,
    golden_dir: Path,
    results_dir: Path,
    repo_root: Path,
    vg_start: float,
    vg_step: float,
    policy: LossPolicy,
    fit_engine: FitEnginePolicy,
    analysis_defaults: dict[str, Any],
    strategy_jobs: int = 1,
) -> FitResult:
    golden = load_golden_device(golden_dir / name)
    vg_start_fit, vg_step_fit = _vg_grid_for_golden(
        golden, vg_start=vg_start, vg_step=vg_step
    )
    model_root = _model_dir(results_dir, model.name)
    fit_dir = model_root / "fit"
    fit_dir.mkdir(parents=True, exist_ok=True)
    work_dir = fit_dir / "_work" / name
    init_params = _warm_start_params(
        model=model,
        name=name,
        golden_dir=golden_dir,
        fit_dir=fit_dir,
        fit_engine=fit_engine,
    )
    strategy_label = fit_engine.strategy
    if init_params:
        strategy_label = f"{strategy_label}+warm_start"
    print(f"  fitting {model.name} on {name} [{strategy_label}] ...")
    result = fit_model_to_golden(
        model=model,
        golden=golden,
        work_dir=work_dir,
        seed=13,
        vg_start=vg_start_fit,
        vg_step=vg_step_fit,
        policy=policy,
        refine=True,
        results_dir=results_dir,
        analysis_defaults=analysis_defaults,
        engine=fit_engine,
        init_params=init_params,
        repo_root=repo_root,
        strategy_jobs=strategy_jobs,
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
    if result.history:
        write_fit_history_csv(fit_dir / f"{name}_history.csv", result)
        write_error_vs_iteration_plot(
            fit_dir / f"{name}_error_vs_iter.png",
            result,
        )
    write_idvg_fit_overlay_plot(
        fit_dir / f"{name}_idvg_fit.png",
        golden=golden,
        model=model,
        parameters=result.parameters,
        vg_start=vg_start_fit,
        vg_step=vg_step_fit,
        work_dir=work_dir / "idvg_plot",
    )
    print(
        f"    err={result.weighted_error:.4g} "
        f"wall={result.fit_wall_s:.2f}s -> {card_path}"
    )
    if fit_engine.strategy != "benchmark" and work_dir.exists():
        shutil.rmtree(work_dir)
    return result


def _predict_one_card(
    *,
    model: ModelSpec,
    card_path: Path,
    benches_dir: Path,
    analyses: tuple[str, ...],
    simulators: tuple[str, ...],
    inner_jobs: int,
) -> list[dict[str, Any]]:
    card = json.loads(card_path.read_text())
    pdk = str(card["pdk"])
    out = benches_dir / pdk
    print(f"  predict {model.name}/{pdk} on {simulators} ...")
    return run_predict_benches(
        model=model,
        card=card,
        output_dir=out,
        analyses=analyses,
        simulators=simulators,
        jobs=inner_jobs,
    )


def main() -> None:
    """Run golden → fit → predict pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=release_root() / "config/golden_suite.json",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=release_root() / "results",
    )
    parser.add_argument(
        "--openvaf-binary",
        type=Path,
        default=release_root() / "work/openvaf-r",
    )
    parser.add_argument("--skip-golden", action="store_true")
    parser.add_argument("--skip-fit", action="store_true")
    parser.add_argument("--skip-predict", action="store_true")
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument(
        "--jobs",
        type=int,
        default=4,
        help="Max concurrent ngspice workers (golden, fit, predict, eval refs).",
    )
    parser.add_argument(
        "--simulators",
        type=str,
        default=None,
        help="Override predict simulators (comma list).",
    )
    parser.add_argument(
        "--fit-strategy",
        type=str,
        default=None,
        help="Override fit_engine.strategy (optuna, optuna_cmaes, optuna_gp, optuna_qmc, optuna_random, differential_evolution, dual_annealing, lbfgsb, staged, staged_optuna, staged_cmaes, benchmark).",
    )
    parser.add_argument(
        "--fit-benchmark",
        type=str,
        default=None,
        help="Run strategy comparison: comma list (sets strategy=benchmark).",
    )
    parser.add_argument(
        "--strategy-jobs",
        type=int,
        default=None,
        help="Concurrent strategies per target in benchmark mode (default: auto from --jobs).",
    )
    parser.add_argument(
        "--targets",
        type=str,
        default=None,
        help="Comma-separated target ids to run (default: all targets in config).",
    )
    parser.add_argument(
        "--fit-models",
        type=str,
        default=None,
        help="Override config fit_models (comma list, e.g. acm4,acm5,qlaw_gm_j14).",
    )
    args = parser.parse_args()
    if args.jobs < 1:
        raise SystemExit(f"--jobs must be >= 1, got {args.jobs}")
    if args.strategy_jobs is not None and args.strategy_jobs < 1:
        raise SystemExit(f"--strategy-jobs must be >= 1, got {args.strategy_jobs}")

    repo_root = release_root()
    results_dir = args.results_dir
    golden_dir = results_dir / "golden"
    cfg = load_golden_config(args.config, repo_root)
    targets = cfg["_targets"]
    if args.targets is not None:
        selected = tuple(s.strip() for s in args.targets.split(",") if s.strip())
        if not selected:
            raise SystemExit("--targets requires at least one target id")
        unknown = sorted(set(selected) - set(targets))
        if unknown:
            raise SystemExit(f"unknown targets in --targets: {', '.join(unknown)}")
        targets = {name: targets[name] for name in selected}
        cfg["_targets"] = targets
    if args.fit_models is not None:
        model_names = tuple(s.strip() for s in args.fit_models.split(",") if s.strip())
        if not model_names:
            raise SystemExit("--fit-models requires at least one model id")
    else:
        model_names = tuple(cfg["fit_models"])
    models = resolve_models(repo_root, model_names)
    policy = loss_policy_from_mapping(cfg["fit_loss"])
    if args.iterations is not None:
        policy = loss_policy_from_mapping(
            {**policy.to_dict(), "optuna_trials": int(args.iterations)}
        )
    fit_engine = fit_engine_from_mapping(cfg.get("fit_engine"))
    if args.fit_benchmark:
        strategies = tuple(
            s.strip() for s in args.fit_benchmark.split(",") if s.strip()
        )
        if not strategies:
            raise SystemExit("--fit-benchmark requires a comma-separated strategy list")
        fit_engine = FitEnginePolicy(
            strategy="benchmark",
            strategies=strategies,
            fit_profile=fit_engine.fit_profile,
            optuna_trials=fit_engine.optuna_trials,
            refine_starts=fit_engine.refine_starts,
            refine_maxiter=fit_engine.refine_maxiter,
            optuna_box_fraction=fit_engine.optuna_box_fraction,
            warm_start=fit_engine.warm_start,
        )
    elif args.fit_strategy:
        fit_engine = FitEnginePolicy(
            strategy=args.fit_strategy,
            strategies=fit_engine.strategies,
            fit_profile=fit_engine.fit_profile,
            optuna_trials=fit_engine.optuna_trials,
            refine_starts=fit_engine.refine_starts,
            refine_maxiter=fit_engine.refine_maxiter,
            optuna_box_fraction=fit_engine.optuna_box_fraction,
            warm_start=fit_engine.warm_start,
        )
    analysis_defaults = cfg.get("analysis_defaults", {})
    analyses = tuple(cfg["predict_analyses"])
    sims = tuple(
        s.strip()
        for s in (args.simulators or ",".join(cfg["predict_simulators"])).split(",")
        if s.strip()
    )
    vg_start = float(cfg["vg_start"])
    vg_step = float(cfg["vg_step"])
    vds_fractions = [float(x) for x in cfg["vds_fractions"]]

    compiled: set[Path] = set()
    for model in models:
        if model.va_path in compiled:
            continue
        _compile_osdi(model.va_path, model.osdi_path, args.openvaf_binary)
        compiled.add(model.va_path)

    if not args.skip_golden:
        print(f"=== Step 1: build golden I-V from PDK BSIM (jobs={args.jobs}) ===")
        with ThreadPoolExecutor(
            max_workers=min(args.jobs, len(targets))
        ) as pool:
            futures = {
                pool.submit(
                    _capture_one_golden,
                    name=name,
                    target=target,
                    golden_dir=golden_dir,
                    vg_start=vg_start,
                    vg_step=vg_step,
                    vds_fractions=vds_fractions,
                ): name
                for name, target in targets.items()
                if not target.data_only
            }
            for fut in as_completed(futures):
                fut.result()

    if policy.weight_ac > 0.0 or policy.weight_noise > 0.0:
        print(
            f"=== Step 1b: capture eval golden AC/noise refs "
            f"(jobs={args.jobs}) ==="
        )
        eval_suite = load_suite_config(release_root() / "config/eval_suite.json", release_root())
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
            jobs=args.jobs,
        )

    fit_by_model: dict[str, list[FitResult]] = {m.name: [] for m in models}
    strategy_jobs = 1
    target_jobs = args.jobs
    if not args.skip_fit and fit_engine.strategy == "benchmark":
        n_strategies = len(fit_engine.strategies)
        if args.strategy_jobs is None:
            strategy_jobs = 1
        else:
            strategy_jobs = min(n_strategies, args.strategy_jobs)
        # Benchmark mode: run one target and one strategy at a time (Optuna/SciPy deadlock in threads).
        strategy_jobs = min(n_strategies, strategy_jobs)
        target_jobs = 1
        print(
            f"  benchmark parallelism: target_jobs={target_jobs} "
            f"strategy_jobs={strategy_jobs} "
            f"(~{target_jobs * strategy_jobs} concurrent ngspice workers)"
        )
    if not args.skip_fit:
        target_names = tuple(targets.keys())
        waves = fit_job_waves(
            target_names,
            golden_dir=golden_dir,
            warm_start=fit_engine.warm_start,
            load_golden_device=load_golden_device,
        )
        n_jobs = sum(len(wave) * len(models) for wave in waves)
        print(
            f"=== Step 2: fit ACM to golden I-V "
            f"({n_jobs} jobs, strategy={fit_engine.strategy}, "
            f"profile={fit_engine.fit_profile}, jobs={target_jobs}) ==="
        )
        for wave_idx, wave in enumerate(waves, start=1):
            fit_jobs: list[tuple[ModelSpec, str]] = []
            for name in wave:
                for model in models:
                    if fit_engine.strategy == "benchmark":
                        bench_dir = results_dir / "fit_benchmark" / model.name
                        card_path = _model_dir(results_dir, model.name) / "fit" / f"{name}.json"
                        if (
                            benchmark_target_complete(
                                bench_dir,
                                name,
                                fit_engine.strategies,
                            )
                            and card_path.is_file()
                        ):
                            print(f"  skip {model.name} on {name} [benchmark complete]")
                            fit_by_model[model.name].append(
                                fit_result_from_fitted_card(card_path)
                            )
                            continue
                    fit_jobs.append((model, name))
            if len(waves) > 1:
                print(f"  wave {wave_idx}/{len(waves)}: {', '.join(wave)}")
            if not fit_jobs:
                continue
            with ThreadPoolExecutor(
                max_workers=min(target_jobs, len(fit_jobs))
            ) as pool:
                futures = {
                    pool.submit(
                        _fit_one_target,
                        model=model,
                        name=name,
                        golden_dir=golden_dir,
                        results_dir=results_dir,
                        repo_root=repo_root,
                        vg_start=vg_start,
                        vg_step=vg_step,
                        policy=policy,
                        fit_engine=fit_engine,
                        analysis_defaults=analysis_defaults,
                        strategy_jobs=strategy_jobs,
                    ): (model.name, name)
                    for model, name in fit_jobs
                }
                for fut in as_completed(futures):
                    result = fut.result()
                    fit_by_model[result.model].append(result)

        if fit_engine.strategy == "benchmark":
            benchmark_rows: list[dict[str, Any]] = []
            for model in models:
                benchmark_rows.extend(
                    collect_benchmark_rows(results_dir, model.name)
                )
            if benchmark_rows:
                write_fit_benchmark_summary(
                    results_dir / "FIT_BENCHMARK.md",
                    rows=benchmark_rows,
                )
                print(f"  {results_dir / 'FIT_BENCHMARK.md'}")

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
                    "fit_strategy": r.fit_strategy,
                    "fit_profile": r.fit_profile,
                }
                for r in results
            ]
            (fit_dir / "fit_summary.json").write_text(
                json.dumps(fit_rows, indent=2) + "\n"
            )

    if not args.skip_predict:
        model_map = {m.name: m for m in models}
        predict_jobs: list[tuple[ModelSpec, Path, Path]] = []
        for model in models:
            fit_dir = results_dir / model.name / "fit"
            card_files = sorted(fit_dir.glob("*.json"))
            card_files = [p for p in card_files if p.name != "fit_summary.json"]
            if not card_files:
                raise FileNotFoundError(f"no fitted cards in {fit_dir}")
            benches_dir = _model_dir(results_dir, model.name) / "benches"
            for card_path in card_files:
                predict_jobs.append((model_map[model.name], card_path, benches_dir))

        inner_jobs = 1 if len(predict_jobs) > 1 else args.jobs
        print(
            f"=== Step 3: predict benches from fitted cards "
            f"({len(predict_jobs)} cards, jobs={args.jobs}) ==="
        )
        all_pred: list[dict] = []
        model_rows_by_name: dict[str, list[dict]] = {m.name: [] for m in models}
        with ThreadPoolExecutor(
            max_workers=min(args.jobs, len(predict_jobs))
        ) as pool:
            futures = {
                pool.submit(
                    _predict_one_card,
                    model=model,
                    card_path=card_path,
                    benches_dir=benches_dir,
                    analyses=analyses,
                    simulators=sims,
                    inner_jobs=inner_jobs,
                ): (model.name, card_path)
                for model, card_path, benches_dir in predict_jobs
            }
            for fut in as_completed(futures):
                model_name, _card_path = futures[fut]
                rows = fut.result()
                model_rows_by_name[model_name].extend(rows)
                all_pred.extend(rows)

        for model in models:
            rows = model_rows_by_name[model.name]
            if not rows:
                continue
            benches_dir = _model_dir(results_dir, model.name) / "benches"
            (benches_dir / "summary.json").write_text(
                json.dumps(rows, indent=2) + "\n"
            )
        n_fail = sum(1 for row in all_pred if not row["ok"])
        print(f"  predict jobs={len(all_pred)} failed={n_fail}")
        if n_fail:
            # Temp OP at 0 °C is flaky for some ACM-5 cards; keep going so
            # fit/eval lanes still complete. Failures remain in SUMMARY.md.
            print(
                f"  WARNING: {n_fail} predict bench(es) failed; continuing",
                flush=True,
            )

    print("=== Step 4: write SUMMARY.md + per-model REPORT.md ===")
    reports = write_regression_reports(repo_root=release_root(), results_dir=results_dir)
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
