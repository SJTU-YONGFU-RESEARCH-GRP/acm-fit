"""Fit ACM DC parameters to golden PDK Id–Vg curves."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np
import optuna
from optuna.samplers import TPESampler
from scipy.optimize import minimize

from acm_eval.export import export_ngspice_waveform
from acm_eval.metrics import compare_to_golden
from acm_eval.netlists import format_instance_params, write_acm_ngspice
from acm_eval.config import PdkEvalConfig
from acm_eval.waveforms import load_xy_csv
from acm_golden import GoldenDevice
from acm_opt.loss import (
    LossPolicy,
    composite_objective,
    dc_curve_residuals,
    loss_policy_from_mapping,
)
from acm_opt.models import ModelSpec
from acm_opt.params import (
    LOG_SCALE_PARAMS,
    bounds_for_model,
    expand_instance_params,
    format_spice_instance_params,
    validate_dc_fit_params,
    validate_dc_fit_policy,
)

optuna.logging.set_verbosity(optuna.logging.WARNING)
_TIME_RE = re.compile(r"^ACM_TIME\s+([0-9.eE+-]+)\s+(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class FitHistoryPoint:
    """One optimization evaluation for error-vs-iteration reporting."""

    iteration: int
    weighted_error: float
    best_weighted_error: float
    phase: str


@dataclass(frozen=True)
class FitResult:
    """Fitted card and error metrics for one model/PDK."""

    pdk: str
    model: str
    parameters: dict[str, float]
    weighted_error: float
    rmse_linear: float
    rmse_log: float
    fit_wall_s: float
    n_evals: int
    peak_rss_kb: int
    history: tuple[FitHistoryPoint, ...] = field(default_factory=tuple)
    loss_policy: dict[str, Any] = field(default_factory=dict)
    rmse_ac: float | None = None
    rmse_noise: float | None = None
    rmse_temp: float | None = None
    dc_loss: float | None = None


@dataclass(frozen=True)
class _DynBenchRefs:
    """Optional AC/noise/temp golden waveforms for multi-objective fitting."""

    ac_csv: Path | None
    noise_csv: Path | None
    temp_csv: Path | None
    ac_params: Mapping[str, Any]
    noise_params: Mapping[str, Any]
    temp_params: Mapping[str, Any]
    ref_vm_max: float | None
    ref_onoise_max: float | None
    ref_temp_max: float | None


def _bounds(width_m: float, model: ModelSpec) -> dict[str, tuple[float, float]]:
    """Return VA-compatible search bounds for ``model.free_params``."""
    return bounds_for_model(model, width_m)


def _expand_params(
    model: ModelSpec,
    free: Mapping[str, float],
    golden: GoldenDevice,
) -> dict[str, float]:
    """Expand free values into a full instance dict."""
    return expand_instance_params(model, free, golden)


def _instance_line(model: ModelSpec, params: Mapping[str, float]) -> str:
    """Format ACM instance line for Id–Vg fit decks."""
    body = format_spice_instance_params(
        model,
        params,
        width_m=float(params["W"]),
        length_m=float(params["L"]),
    )
    return f"N1 d1 g1 s1 b1 {model.spice_model} {body}"


def _run_acm_idvg(
    *,
    model: ModelSpec,
    params: Mapping[str, float],
    vds: float,
    vdd: float,
    vg_start: float,
    vg_step: float,
    work_dir: Path,
    polarity: str = "nmos",
) -> tuple[np.ndarray, np.ndarray, float, int]:
    """Simulate ACM Id-Vg at one |VDS|; return vg, id, runtime, rss."""
    work_dir.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    netlist = work_dir / f"acm_{tag}.spice"
    out = (work_dir / f"acm_{tag}.txt").resolve()
    if polarity == "pmos":
        vg_stop = -vdd
        step = -abs(vg_step)
        bias = f"""VDD vdd 0 DC {vdd}
VG1 g1 0 DC 0
VS1 s1 vdd 0 DC 0
VB1 b1 vdd 0 DC 0
VD1 d1 0 DC {vdd - vds}"""
        dc_line = f"dc VG1 {vg_start} {vg_stop} {step}"
    else:
        bias = f"""VG1 g1 0 DC 0
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vds}"""
        dc_line = f"dc VG1 {vg_start} {vdd} {vg_step}"
    netlist.write_text(
        f"""* ACM fit eval polarity={polarity}
.model {model.spice_model} {model.module_name}
{bias}
{_instance_line(model, params)}
.control
pre_osdi {model.osdi_path.resolve()}
{dc_line}
wrdata {out} abs(i(VS1))
.endc
.end
"""
    )
    proc = subprocess.run(
        [
            "/usr/bin/time",
            "-f",
            "ACM_TIME %e %M",
            "ngspice",
            "-b",
            str(netlist.resolve()),
        ],
        cwd=str(work_dir),
        check=False,
        capture_output=True,
        text=True,
    )
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    netlist.with_suffix(".log").write_text(text)
    match = _TIME_RE.search(text)
    if match is None or proc.returncode != 0 or not out.is_file():
        tail = "\n".join(text.strip().splitlines()[-20:])
        raise RuntimeError(f"ACM sim failed: {netlist}\n{tail}")
    raw = np.loadtxt(out)
    return raw[:, 0], raw[:, 1], float(match.group(1)), int(match.group(2))


def _pdk_stub(golden: GoldenDevice) -> PdkEvalConfig:
    """Minimal PDK stub for shared ACM netlist helpers."""
    return PdkEvalConfig(
        name=golden.pdk,
        vdd=golden.vdd,
        width="",
        length="",
        width_m=golden.width_m,
        length_m=golden.length_m,
        sections={"ngspice": ""},
        ref_devices={"ngspice": ""},
    )


def _run_acm_analysis_csv(
    *,
    model: ModelSpec,
    params: Mapping[str, float],
    golden: GoldenDevice,
    analysis: str,
    analysis_params: Mapping[str, Any],
    work_dir: Path,
) -> tuple[Path, int]:
    """Run one ACM-only analysis and export ``acm.csv``; return path + RSS."""
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / ".spiceinit").write_text("set ngbehavior=hs\n")
    tag = uuid.uuid4().hex[:8]
    net = work_dir / f"{analysis}_{tag}.spice"
    raw = work_dir / f"{analysis}_{tag}_out.txt"
    csv_path = work_dir / f"{analysis}_{tag}.csv"
    pdk = _pdk_stub(golden)
    inst = format_instance_params(model, params, pdk)
    write_acm_ngspice(
        path=net,
        title=f"fit {analysis}",
        model=model,
        params=inst,
        osdi=model.osdi_path.resolve(),
        analysis=analysis,
        analysis_params=analysis_params,
        vdd=golden.vdd,
        out_txt=raw.resolve(),
    )
    proc = subprocess.run(
        [
            "/usr/bin/time",
            "-f",
            "ACM_TIME %e %M",
            "ngspice",
            "-b",
            str(net.resolve()),
        ],
        cwd=str(work_dir),
        check=False,
        capture_output=True,
        text=True,
    )
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    (work_dir / f"{analysis}_{tag}.log").write_text(text)
    match = _TIME_RE.search(text)
    if match is None or proc.returncode != 0 or not raw.is_file():
        raise RuntimeError(f"ACM {analysis} sim failed in {work_dir}")
    export_ngspice_waveform(analysis=analysis, raw_path=raw, csv_path=csv_path)
    return csv_path, int(match.group(2))


def load_dyn_bench_refs(
    *,
    results_dir: Path,
    pdk: str,
    policy: LossPolicy,
    analysis_defaults: Mapping[str, Mapping[str, Any]],
) -> _DynBenchRefs:
    """Load golden AC/noise/temp refs required by the loss policy."""
    ac_csv = noise_csv = temp_csv = None
    ref_vm_max = ref_onoise_max = ref_temp_max = None
    ac_params = dict(analysis_defaults.get("ac", {}))
    noise_params = dict(analysis_defaults.get("noise", {}))
    temp_params = dict(analysis_defaults.get("temp", {}))
    if policy.weight_ac > 0.0:
        ac_csv = results_dir / "golden" / pdk / "ref" / "ac" / "ref.csv"
        if not ac_csv.is_file():
            raise FileNotFoundError(
                f"AC loss enabled but missing golden ref {ac_csv}; "
                "run eval golden capture first"
            )
        if "rd_ohm" not in ac_params:
            raise ValueError("analysis_defaults.ac missing rd_ohm")
        _, y = load_xy_csv(ac_csv)
        ref_vm_max = float(np.max(np.abs(y)))
        if ref_vm_max <= 0.0:
            raise ValueError(f"degenerate AC golden ref: {ac_csv}")
    if policy.weight_noise > 0.0:
        noise_csv = results_dir / "golden" / pdk / "ref" / "noise" / "ref.csv"
        if not noise_csv.is_file():
            raise FileNotFoundError(
                f"noise loss enabled but missing golden ref {noise_csv}; "
                "run eval golden capture first"
            )
        if "rd_ohm" not in noise_params:
            raise ValueError("analysis_defaults.noise missing rd_ohm")
        _, y = load_xy_csv(noise_csv)
        ref_onoise_max = float(np.max(np.abs(y)))
        if ref_onoise_max <= 0.0:
            raise ValueError(f"degenerate noise golden ref: {noise_csv}")
    if policy.weight_temp > 0.0:
        temp_csv = results_dir / "golden" / pdk / "ref" / "temp" / "ref.csv"
        if not temp_csv.is_file():
            raise FileNotFoundError(
                f"temp loss enabled but missing golden ref {temp_csv}; "
                "run eval golden capture first"
            )
        if "temps_c" not in temp_params:
            raise ValueError("analysis_defaults.temp missing temps_c")
        _, y = load_xy_csv(temp_csv)
        ref_temp_max = float(np.max(np.abs(y)))
        if ref_temp_max <= 0.0:
            raise ValueError(f"degenerate temp golden ref: {temp_csv}")
    return _DynBenchRefs(
        ac_csv=ac_csv,
        noise_csv=noise_csv,
        temp_csv=temp_csv,
        ac_params=ac_params,
        noise_params=noise_params,
        temp_params=temp_params,
        ref_vm_max=ref_vm_max,
        ref_onoise_max=ref_onoise_max,
        ref_temp_max=ref_temp_max,
    )


def _score_params(
    model: ModelSpec,
    free: Mapping[str, float],
    golden: GoldenDevice,
    *,
    vg_start: float,
    vg_step: float,
    policy: LossPolicy,
    work_dir: Path,
    dyn: _DynBenchRefs | None,
) -> tuple[float, float, float, float, float | None, float | None, float | None, int]:
    """Score one parameter set.

    Returns:
        objective, rmse_linear, rmse_log, dc_loss, rmse_ac, rmse_noise,
        rmse_temp, peak_rss
    """
    params = _expand_params(model, free, golden)
    polarity = str(golden.meta.get("polarity", "nmos"))
    lin_errs: list[float] = []
    log_errs: list[float] = []
    dc_errs: list[float] = []
    peak_rss = 0
    for curve in golden.curves:
        vg_acm, id_acm, _, rss = _run_acm_idvg(
            model=model,
            params=params,
            vds=curve.vds,
            vdd=golden.vdd,
            vg_start=vg_start,
            vg_step=vg_step,
            work_dir=work_dir,
            polarity=polarity,
        )
        if id_acm.shape != curve.id_ref.shape:
            raise ValueError("ACM/golden length mismatch")
        lin, log, dc = dc_curve_residuals(
            curve.vg if curve.vg.shape == vg_acm.shape else vg_acm,
            curve.id_ref,
            id_acm,
            policy=policy,
            vt0=float(params["VT0"]),
        )
        lin_errs.append(lin)
        log_errs.append(log)
        dc_errs.append(dc)
        peak_rss = max(peak_rss, rss)

    dc_loss = float(np.mean(dc_errs))
    rmse_ac: float | None = None
    rmse_noise: float | None = None
    rmse_temp: float | None = None
    if dyn is not None and policy.weight_ac > 0.0:
        assert dyn.ac_csv is not None
        acm_csv, rss = _run_acm_analysis_csv(
            model=model,
            params=params,
            golden=golden,
            analysis="ac",
            analysis_params=dyn.ac_params,
            work_dir=work_dir / "ac",
        )
        peak_rss = max(peak_rss, rss)
        metrics = compare_to_golden("ac", dyn.ac_csv, acm_csv)
        rmse_ac = float(metrics["rmse_vm"])
    if dyn is not None and policy.weight_noise > 0.0:
        assert dyn.noise_csv is not None
        acm_csv, rss = _run_acm_analysis_csv(
            model=model,
            params=params,
            golden=golden,
            analysis="noise",
            analysis_params=dyn.noise_params,
            work_dir=work_dir / "noise",
        )
        peak_rss = max(peak_rss, rss)
        metrics = compare_to_golden("noise", dyn.noise_csv, acm_csv)
        rmse_noise = float(metrics["rmse_onoise"])
    if dyn is not None and policy.weight_temp > 0.0:
        assert dyn.temp_csv is not None
        acm_csv, rss = _run_acm_analysis_csv(
            model=model,
            params=params,
            golden=golden,
            analysis="temp",
            analysis_params=dyn.temp_params,
            work_dir=work_dir / "temp",
        )
        peak_rss = max(peak_rss, rss)
        metrics = compare_to_golden("temp", dyn.temp_csv, acm_csv)
        rmse_temp = float(metrics["rmse_linear"])

    objective = composite_objective(
        dc_loss=dc_loss,
        ac_rmse=rmse_ac,
        noise_rmse=rmse_noise,
        temp_rmse=rmse_temp,
        ref_vm_max=None if dyn is None else dyn.ref_vm_max,
        ref_onoise_max=None if dyn is None else dyn.ref_onoise_max,
        ref_temp_max=None if dyn is None else dyn.ref_temp_max,
        policy=policy,
    )
    return (
        objective,
        float(np.mean(lin_errs)),
        float(np.mean(log_errs)),
        dc_loss,
        rmse_ac,
        rmse_noise,
        rmse_temp,
        peak_rss,
    )


def _append_history(
    history: list[FitHistoryPoint],
    *,
    weighted_error: float,
    phase: str,
) -> None:
    """Append one evaluation and update best-so-far."""
    best = (
        weighted_error
        if not history
        else min(history[-1].best_weighted_error, weighted_error)
    )
    history.append(
        FitHistoryPoint(
            iteration=len(history) + 1,
            weighted_error=weighted_error,
            best_weighted_error=best,
            phase=phase,
        )
    )


def fit_model_to_golden(
    *,
    model: ModelSpec,
    golden: GoldenDevice,
    work_dir: Path,
    seed: int,
    vg_start: float,
    vg_step: float,
    policy: LossPolicy,
    refine: bool = True,
    results_dir: Path | None = None,
    analysis_defaults: Mapping[str, Mapping[str, Any]] | None = None,
    iterations: int | None = None,
    weight_linear: float | None = None,
    weight_log: float | None = None,
) -> FitResult:
    """Optuna (+ multi-start L-BFGS-B) fit of one ACM model to golden data.

    Args:
        policy: Loss / optimizer policy. If ``weight_linear`` / ``weight_log``
            are passed (legacy), they override the corresponding policy fields.
        iterations: Optional override for ``policy.optuna_trials``.
    """
    if not model.osdi_path.is_file():
        raise FileNotFoundError(f"missing OSDI: {model.osdi_path}")
    validate_dc_fit_params(model)
    validate_dc_fit_policy(policy)
    if weight_linear is not None or weight_log is not None:
        overrides: dict[str, Any] = dict(policy.to_dict())
        if weight_linear is not None:
            overrides["weight_linear"] = float(weight_linear)
        if weight_log is not None:
            overrides["weight_log"] = float(weight_log)
        policy = loss_policy_from_mapping(overrides)
    if iterations is not None:
        policy = loss_policy_from_mapping(
            {**policy.to_dict(), "optuna_trials": int(iterations)}
        )

    dyn: _DynBenchRefs | None = None
    # Golden fit is DC-only; dyn benches are not loaded.

    bounds = _bounds(golden.width_m, model)
    free_names = model.free_params
    work_dir.mkdir(parents=True, exist_ok=True)
    n_evals = 0
    peak_rss = 0
    history: list[FitHistoryPoint] = []
    t0 = time.perf_counter()

    def score(free: Mapping[str, float], phase: str) -> float:
        nonlocal n_evals, peak_rss
        obj, _, _, _, _, _, _, rss = _score_params(
            model,
            free,
            golden,
            vg_start=vg_start,
            vg_step=vg_step,
            policy=policy,
            work_dir=work_dir / phase,
            dyn=dyn,
        )
        n_evals += 1
        peak_rss = max(peak_rss, rss)
        _append_history(history, weighted_error=obj, phase=phase)
        return obj

    def objective(trial: optuna.Trial) -> float:
        free: dict[str, float] = {}
        for name in free_names:
            lo, hi = bounds[name]
            free[name] = trial.suggest_float(
                name,
                lo,
                hi,
                log=name in LOG_SCALE_PARAMS,
            )
        return score(free, "optuna")

    study = optuna.create_study(
        direction="minimize",
        sampler=TPESampler(seed=seed + len(free_names)),
    )
    study.optimize(objective, n_trials=policy.optuna_trials, show_progress_bar=False)

    starts: list[dict[str, float]] = []
    seen: set[tuple[float, ...]] = set()
    for trial in sorted(study.trials, key=lambda t: float(t.value if t.value is not None else 1e300)):
        if trial.value is None:
            continue
        free = {name: float(trial.params[name]) for name in free_names}
        key = tuple(round(free[n], 12) for n in free_names)
        if key in seen:
            continue
        seen.add(key)
        starts.append(free)
        if len(starts) >= max(1, policy.refine_starts):
            break
    if not starts:
        starts = [{name: float(study.best_trial.params[name]) for name in free_names}]

    free_best = dict(starts[0])
    best_obj = float("inf")

    if refine and policy.refine_starts > 0:
        box = [(bounds[n][0], bounds[n][1]) for n in free_names]
        for start in starts:
            x0 = np.array([start[n] for n in free_names], dtype=float)

            def local_obj(x: np.ndarray) -> float:
                free = {n: float(v) for n, v in zip(free_names, x)}
                return score(free, "refine")

            result = minimize(
                local_obj,
                x0=x0,
                method="L-BFGS-B",
                bounds=box,
                options={
                    "maxiter": policy.refine_maxiter,
                    "ftol": 1e-6,
                    "eps": 1e-3,
                },
            )
            cand = {n: float(v) for n, v in zip(free_names, result.x)}
            obj = score(cand, "refine_pick")
            if obj < best_obj:
                best_obj = obj
                free_best = cand
    else:
        free_best = {name: float(study.best_trial.params[name]) for name in free_names}

    obj, lin, log, dc_loss, rmse_ac, rmse_noise, rmse_temp, rss = _score_params(
        model,
        free_best,
        golden,
        vg_start=vg_start,
        vg_step=vg_step,
        policy=policy,
        work_dir=work_dir / "best",
        dyn=dyn,
    )
    peak_rss = max(peak_rss, rss)
    n_evals += 1
    _append_history(history, weighted_error=obj, phase="final")
    params = _expand_params(model, free_best, golden)
    return FitResult(
        pdk=golden.pdk,
        model=model.name,
        parameters=params,
        weighted_error=obj,
        rmse_linear=lin,
        rmse_log=log,
        fit_wall_s=time.perf_counter() - t0,
        n_evals=n_evals,
        peak_rss_kb=peak_rss,
        history=tuple(history),
        loss_policy=policy.to_dict(),
        rmse_ac=rmse_ac,
        rmse_noise=rmse_noise,
        rmse_temp=rmse_temp,
        dc_loss=dc_loss,
    )


def write_fit_history_csv(path: Path, result: FitResult) -> None:
    """Write per-iteration weighted error history as CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "pdk",
                "model",
                "iteration",
                "phase",
                "weighted_error",
                "best_weighted_error",
            ]
        )
        for point in result.history:
            writer.writerow(
                [
                    result.pdk,
                    result.model,
                    point.iteration,
                    point.phase,
                    f"{point.weighted_error:.8g}",
                    f"{point.best_weighted_error:.8g}",
                ]
            )


def write_error_vs_iteration_plot(
    path: Path,
    result: FitResult,
) -> None:
    """Plot trial error and best-so-far vs iteration for one fit."""
    if not result.history:
        raise ValueError(f"no fit history for {result.pdk}/{result.model}")
    iters = [p.iteration for p in result.history]
    trial_err = [p.weighted_error for p in result.history]
    best_err = [p.best_weighted_error for p in result.history]

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.scatter(iters, trial_err, s=22, alpha=0.45, color="#7f7f7f", label="trial")
    ax.plot(iters, best_err, color="#1f77b4", linewidth=2.0, label="best so far")
    refine_iters = [p.iteration for p in result.history if p.phase == "refine"]
    if refine_iters:
        ax.axvline(
            min(refine_iters) - 0.5,
            color="#d62728",
            linestyle="--",
            linewidth=1.0,
            label="refine start",
        )
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Objective")
    ax.set_title(f"{result.pdk} / {result.model}")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_combined_error_vs_iteration_plot(
    path: Path,
    results: Sequence[FitResult],
) -> None:
    """Overlay best-so-far curves for all PDK/model fits."""
    if not results:
        raise ValueError("no fit results to plot")
    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    cmap = plt.get_cmap("tab10")
    for idx, result in enumerate(results):
        if not result.history:
            raise ValueError(f"no fit history for {result.pdk}/{result.model}")
        iters = [p.iteration for p in result.history]
        best_err = [p.best_weighted_error for p in result.history]
        ax.plot(
            iters,
            best_err,
            linewidth=2.0,
            color=cmap(idx % 10),
            label=f"{result.pdk}:{result.model}",
        )
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Best objective so far")
    ax.set_title("Golden fit: error vs iteration")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_fitted_card(
    path: Path,
    result: FitResult,
    *,
    vdd: float | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Write fitted parameter card JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "pdk": result.pdk,
        "model": result.model,
        "parameters": result.parameters,
        "weighted_error": result.weighted_error,
        "rmse_linear": result.rmse_linear,
        "rmse_log": result.rmse_log,
        "dc_loss": result.dc_loss,
        "rmse_ac": result.rmse_ac,
        "rmse_noise": result.rmse_noise,
        "rmse_temp": result.rmse_temp,
        "loss_policy": result.loss_policy,
        "fit_wall_s": result.fit_wall_s,
        "n_evals": result.n_evals,
        "peak_rss_kb": result.peak_rss_kb,
        "history": [
            {
                "iteration": p.iteration,
                "phase": p.phase,
                "weighted_error": p.weighted_error,
                "best_weighted_error": p.best_weighted_error,
            }
            for p in result.history
        ],
    }
    if vdd is not None:
        payload["vdd"] = vdd
    if extra:
        payload.update(dict(extra))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


__all__ = [
    "FitHistoryPoint",
    "FitResult",
    "fit_model_to_golden",
    "write_combined_error_vs_iteration_plot",
    "write_error_vs_iteration_plot",
    "write_fit_history_csv",
    "write_fitted_card",
]
