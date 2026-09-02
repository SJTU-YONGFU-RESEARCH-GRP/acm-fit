"""Run multiple fit strategies on the same golden and write comparison reports."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from acm.golden import GoldenDevice
from acm.opt.engine import FitEnginePolicy
from acm.opt.fit import FitResult, write_fitted_card
from acm.opt.loss import LossPolicy
from acm.opt.models import ModelSpec
from acm.opt.strategies import FitSession, run_single_strategy


def _benchmark_markdown(
    *,
    target: str,
    model: str,
    rows: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Fit benchmark — {target} / {model}",
        "",
        "| strategy | weighted_err | rmse_log | fit_wall_s | n_evals |",
        "|----------|-------------:|---------:|-----------:|--------:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['strategy']} "
            f"| {row['weighted_error']:.6g} "
            f"| {row['rmse_log']:.6g} "
            f"| {row['fit_wall_s']:.2f} "
            f"| {row['n_evals']} |"
        )
    best = min(rows, key=lambda r: r["weighted_error"])
    lines.extend(
        [
            "",
            f"**Best:** `{best['strategy']}` "
            f"(weighted_err={best['weighted_error']:.6g})",
            "",
        ]
    )
    return "\n".join(lines)


def collect_benchmark_rows(results_dir: Path, model_name: str) -> list[dict[str, Any]]:
    """Load per-target benchmark JSON files into lane-level rows."""
    bench_dir = results_dir / "fit_benchmark" / model_name
    if not bench_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(bench_dir.glob("*.json")):
        for entry in json.loads(path.read_text()):
            rows.append({"target": path.stem, **entry})
    return rows


def _checkpoint_path(work_dir: Path, strategy: str) -> Path:
    return work_dir / strategy / "benchmark_checkpoint.json"


def _save_checkpoint(path: Path, result: FitResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pdk": result.pdk,
        "model": result.model,
        "parameters": result.parameters,
        "weighted_error": result.weighted_error,
        "rmse_linear": result.rmse_linear,
        "rmse_log": result.rmse_log,
        "fit_wall_s": result.fit_wall_s,
        "n_evals": result.n_evals,
        "peak_rss_kb": result.peak_rss_kb,
        "fit_strategy": result.fit_strategy,
        "fit_profile": result.fit_profile,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _load_checkpoint(path: Path) -> FitResult | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text())
    return FitResult(
        pdk=str(payload["pdk"]),
        model=str(payload["model"]),
        parameters={k: float(v) for k, v in payload["parameters"].items()},
        weighted_error=float(payload["weighted_error"]),
        rmse_linear=float(payload["rmse_linear"]),
        rmse_log=float(payload["rmse_log"]),
        fit_wall_s=float(payload["fit_wall_s"]),
        n_evals=int(payload["n_evals"]),
        peak_rss_kb=int(payload["peak_rss_kb"]),
        fit_strategy=payload.get("fit_strategy"),
        fit_profile=payload.get("fit_profile"),
    )


def _run_benchmark_strategy(
    *,
    strategy: str,
    repo_root: Path,
    model: ModelSpec,
    golden: GoldenDevice,
    work_dir: Path,
    seed: int,
    vg_start: float,
    vg_step: float,
    policy: LossPolicy,
    engine: FitEnginePolicy,
    init_params: Mapping[str, float] | None,
    bounds: Mapping[str, tuple[float, float]],
) -> tuple[str, FitResult]:
    sub_engine = replace(engine, strategy=strategy)
    session = FitSession(
        model=model,
        golden=golden,
        work_dir=work_dir / strategy,
        seed=seed,
        vg_start=vg_start,
        vg_step=vg_step,
        policy=policy,
        engine=sub_engine,
        init_params=init_params,
        bounds=dict(bounds),
        free_names=model.free_params,
    )
    result = run_single_strategy(
        session,
        strategy=strategy,
        repo_root=repo_root,
        profile=None,
    )
    _save_checkpoint(_checkpoint_path(work_dir, strategy), result)
    return strategy, result


def run_fit_benchmark(
    *,
    repo_root: Path,
    model: ModelSpec,
    golden: GoldenDevice,
    work_dir: Path,
    seed: int,
    vg_start: float,
    vg_step: float,
    policy: LossPolicy,
    engine: FitEnginePolicy,
    init_params: Mapping[str, float] | None,
    benchmark_dir: Path,
    strategy_jobs: int = 1,
) -> tuple[FitResult, dict[str, FitResult]]:
    """Run ``engine.strategies`` and return the best result plus all runs."""
    from acm.opt.fit import _bounds

    if engine.strategy != "benchmark":
        raise ValueError("run_fit_benchmark requires engine.strategy=benchmark")
    if strategy_jobs < 1:
        raise ValueError(f"strategy_jobs must be >= 1, got {strategy_jobs}")
    target_json = benchmark_dir / f"{golden.pdk}.json"
    if target_json.is_file():
        rows = json.loads(target_json.read_text())
        cached_from_json = {
            row["strategy"]: _load_checkpoint(_checkpoint_path(work_dir, row["strategy"]))
            for row in rows
        }
        if (
            set(cached_from_json) == set(engine.strategies)
            and all(v is not None for v in cached_from_json.values())
        ):
            best = min(cached_from_json.values(), key=lambda r: r.weighted_error)
            return best, cached_from_json
    results: dict[str, FitResult] = {}
    bounds = _bounds(golden.width_m, model)
    common = {
        "repo_root": repo_root,
        "model": model,
        "golden": golden,
        "work_dir": work_dir,
        "seed": seed,
        "vg_start": vg_start,
        "vg_step": vg_step,
        "policy": policy,
        "engine": engine,
        "init_params": init_params,
        "bounds": bounds,
    }
    pending = [
        s
        for s in engine.strategies
        if _load_checkpoint(_checkpoint_path(work_dir, s)) is None
    ]
    for strategy in engine.strategies:
        cached = _load_checkpoint(_checkpoint_path(work_dir, strategy))
        if cached is not None:
            results[strategy] = cached
    run_kw = {**common, "work_dir": work_dir}
    if not pending:
        pass
    elif strategy_jobs == 1 or len(pending) == 1:
        for strategy in pending:
            name, result = _run_benchmark_strategy(strategy=strategy, **run_kw)
            results[name] = result
    else:
        workers = min(strategy_jobs, len(pending))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_run_benchmark_strategy, strategy=strategy, **run_kw): strategy
                for strategy in pending
            }
            for fut in as_completed(futures):
                name, result = fut.result()
                results[name] = result
    missing = [s for s in engine.strategies if s not in results]
    if missing:
        raise RuntimeError(
            f"benchmark incomplete for {golden.pdk}: missing strategies {missing}"
        )
    best = min(results.values(), key=lambda r: r.weighted_error)
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "strategy": name,
            "weighted_error": res.weighted_error,
            "rmse_log": res.rmse_log,
            "fit_wall_s": res.fit_wall_s,
            "n_evals": res.n_evals,
        }
        for name, res in sorted(results.items())
    ]
    (benchmark_dir / f"{golden.pdk}.json").write_text(
        json.dumps(rows, indent=2) + "\n"
    )
    (benchmark_dir / f"{golden.pdk}.md").write_text(
        _benchmark_markdown(target=golden.pdk, model=model.name, rows=rows)
    )
    return best, results


def write_fit_benchmark_summary(
    path: Path,
    *,
    rows: list[dict[str, Any]],
) -> None:
    """Write lane-level strategy × target comparison table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Fit strategy benchmark",
        "",
        "| target | strategy | weighted_err | rmse_log | fit_wall_s | n_evals |",
        "|--------|----------|-------------:|---------:|-----------:|--------:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['target']} | {row['strategy']} "
            f"| {row['weighted_error']:.6g} "
            f"| {row['rmse_log']:.6g} "
            f"| {row['fit_wall_s']:.2f} "
            f"| {row['n_evals']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines))


def write_benchmark_card(
    path: Path,
    result: FitResult,
    *,
    vdd: float | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Persist the winning benchmark card."""
    write_fitted_card(path, result, vdd=vdd, extra=extra)


__all__ = [
    "collect_benchmark_rows",
    "run_fit_benchmark",
    "write_fit_benchmark_summary",
    "write_benchmark_card",
]
