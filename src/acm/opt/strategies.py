"""Fit search strategies: optuna variants, staged, staged_optuna, benchmark."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

import numpy as np
import optuna
from optuna.samplers import CmaEsSampler, GPSampler, QMCSampler, RandomSampler, TPESampler
from scipy.optimize import differential_evolution, dual_annealing, minimize

optuna.logging.set_verbosity(optuna.logging.WARNING)

_INFEASIBLE_OBJECTIVE = 1.0e300


def _is_sim_failure(exc: BaseException) -> bool:
    if not isinstance(exc, RuntimeError):
        return False
    msg = str(exc)
    return msg.startswith("ACM ") and ("sim failed" in msg or "sim timed out" in msg)


def _study_best_free(
    study: optuna.Study,
    free_names: Sequence[str],
) -> dict[str, float]:
    feasible = [
        trial
        for trial in study.trials
        if trial.value is not None and math.isfinite(float(trial.value))
    ]
    if not feasible:
        raise RuntimeError(
            f"optuna study produced no feasible trials ({len(study.trials)} evaluated)"
        )
    best = min(feasible, key=lambda trial: float(trial.value))
    return {name: float(best.params[name]) for name in free_names}

from acm.golden import GoldenCurve, GoldenDevice
from acm.opt.engine import (
    FIT_PROFILE_STRATEGIES,
    FitEnginePolicy,
    STAGED_SAMPLER_STRATEGIES,
)
from acm.opt.fit import (
    FitHistoryPoint,
    FitResult,
    _append_history,
    _bounds,
    _expand_params,
    _score_params,
)
from acm.opt.loss import LossPolicy, loss_policy_from_mapping
from acm.opt.models import ModelSpec
from acm.opt.params import LOG_SCALE_PARAMS
from acm.opt.profiles import FitProfile, FitStage, resolve_fit_profile


def select_curves(
    golden: GoldenDevice,
    selector: str,
) -> tuple[GoldenCurve, ...]:
    """Select Id–Vg curves for one staged-fit step."""
    if not golden.curves:
        raise ValueError(f"no golden curves for {golden.pdk}")
    ordered = tuple(sorted(golden.curves, key=lambda c: c.vds))
    if selector == "all":
        return ordered
    if selector == "low_vds":
        return (ordered[0],)
    if selector == "mid_vds":
        return (ordered[len(ordered) // 2],)
    if selector == "high_vds":
        return (ordered[-1],)
    raise ValueError(f"unsupported curve selector {selector!r}")


def _initial_free(
    *,
    free_names: Sequence[str],
    bounds: Mapping[str, tuple[float, float]],
    init_params: Mapping[str, float] | None,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in free_names:
        if init_params is not None and name in init_params:
            out[name] = float(init_params[name])
            continue
        lo, hi = bounds[name]
        if name in LOG_SCALE_PARAMS:
            out[name] = math.sqrt(lo * hi)
        else:
            out[name] = 0.5 * (lo + hi)
    return out


def _narrow_bounds(
    center: Mapping[str, float],
    global_bounds: Mapping[str, tuple[float, float]],
    free_names: Sequence[str],
    fraction: float,
) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for name in free_names:
        lo_g, hi_g = global_bounds[name]
        val = float(center[name])
        if name in LOG_SCALE_PARAMS:
            lo = max(lo_g, val * (1.0 - fraction))
            hi = min(hi_g, val * (1.0 + fraction))
        else:
            span = hi_g - lo_g
            lo = max(lo_g, val - fraction * span)
            hi = min(hi_g, val + fraction * span)
        if lo >= hi:
            raise ValueError(
                f"degenerate narrow box for {name}: center={val}, "
                f"global=({lo_g}, {hi_g}), fraction={fraction}"
            )
        out[name] = (lo, hi)
    return out


@dataclass
class FitSession:
    """Mutable state for one golden-fit job."""

    model: ModelSpec
    golden: GoldenDevice
    work_dir: Any
    seed: int
    vg_start: float
    vg_step: float
    policy: LossPolicy
    engine: FitEnginePolicy
    init_params: Mapping[str, float] | None
    bounds: dict[str, tuple[float, float]]
    free_names: tuple[str, ...]
    n_evals: int = 0
    peak_rss: int = 0
    history: list[FitHistoryPoint] | None = None
    t0: float = 0.0

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = []
        if self.t0 == 0.0:
            self.t0 = time.perf_counter()

    def score(
        self,
        free: Mapping[str, float],
        *,
        phase: str,
        policy: LossPolicy | None = None,
        curves: Sequence[GoldenCurve] | None = None,
    ) -> float:
        obj, _, _, _, _, _, _, rss = _score_params(
            self.model,
            free,
            self.golden,
            vg_start=self.vg_start,
            vg_step=self.vg_step,
            policy=policy or self.policy,
            work_dir=self.work_dir / phase,
            dyn=None,
            curves=curves,
        )
        self.n_evals += 1
        self.peak_rss = max(self.peak_rss, rss)
        assert self.history is not None
        _append_history(self.history, weighted_error=obj, phase=phase)
        return obj

    def optimizer_score(
        self,
        free: Mapping[str, float],
        *,
        phase: str,
        policy: LossPolicy | None = None,
        curves: Sequence[GoldenCurve] | None = None,
    ) -> float:
        """Objective for search callbacks; infeasible SPICE points get a large penalty."""
        try:
            return self.score(
                free,
                phase=phase,
                policy=policy,
                curves=curves,
            )
        except RuntimeError as exc:
            if not _is_sim_failure(exc):
                raise
            self.n_evals += 1
            assert self.history is not None
            _append_history(self.history, weighted_error=_INFEASIBLE_OBJECTIVE, phase=phase)
            return _INFEASIBLE_OBJECTIVE

    def finalize(self, free_best: Mapping[str, float]) -> FitResult:
        obj, lin, log, dc_loss, rmse_ac, rmse_noise, rmse_temp, rss = _score_params(
            self.model,
            free_best,
            self.golden,
            vg_start=self.vg_start,
            vg_step=self.vg_step,
            policy=self.policy,
            work_dir=self.work_dir / "best",
            dyn=None,
        )
        self.n_evals += 1
        self.peak_rss = max(self.peak_rss, rss)
        assert self.history is not None
        _append_history(self.history, weighted_error=obj, phase="final")
        params = _expand_params(self.model, free_best, self.golden)
        return FitResult(
            pdk=self.golden.pdk,
            model=self.model.name,
            parameters=params,
            weighted_error=obj,
            rmse_linear=lin,
            rmse_log=log,
            fit_wall_s=time.perf_counter() - self.t0,
            n_evals=self.n_evals,
            peak_rss_kb=self.peak_rss,
            history=tuple(self.history),
            loss_policy=self.policy.to_dict(),
            rmse_ac=rmse_ac,
            rmse_noise=rmse_noise,
            rmse_temp=rmse_temp,
            dc_loss=dc_loss,
            fit_strategy=self.engine.strategy,
            fit_profile=self.engine.fit_profile,
        )


def _effective_engine_policy(
    engine: FitEnginePolicy,
    policy: LossPolicy,
) -> FitEnginePolicy:
    """Merge per-engine trial/refine overrides into a resolved policy view."""
    trials = (
        engine.optuna_trials
        if engine.optuna_trials is not None
        else policy.optuna_trials
    )
    refine_starts = (
        engine.refine_starts
        if engine.refine_starts is not None
        else policy.refine_starts
    )
    refine_maxiter = (
        engine.refine_maxiter
        if engine.refine_maxiter is not None
        else policy.refine_maxiter
    )
    return replace(
        engine,
        optuna_trials=trials,
        refine_starts=refine_starts,
        refine_maxiter=refine_maxiter,
    )


def _run_lbfgsb_refine(
    session: FitSession,
    *,
    free_start: Mapping[str, float],
    bounds: Mapping[str, tuple[float, float]],
    refine_starts: int,
    refine_maxiter: int,
    phase_prefix: str = "refine",
) -> dict[str, float]:
    if refine_starts <= 0:
        return dict(free_start)
    box = [(bounds[n][0], bounds[n][1]) for n in session.free_names]
    starts = [dict(free_start)]
    free_best = dict(free_start)
    best_obj = session.optimizer_score(free_best, phase=f"{phase_prefix}_pick_init")
    for idx in range(refine_starts):
        x0 = np.array(
            [starts[min(idx, len(starts) - 1)][n] for n in session.free_names],
            dtype=float,
        )

        def local_obj(x: np.ndarray) -> float:
            free = {n: float(v) for n, v in zip(session.free_names, x)}
            return session.optimizer_score(free, phase=f"{phase_prefix}")

        result = minimize(
            local_obj,
            x0=x0,
            method="L-BFGS-B",
            bounds=box,
            options={"maxiter": refine_maxiter, "ftol": 1e-6, "eps": 1e-3},
        )
        cand = {n: float(v) for n, v in zip(session.free_names, result.x)}
        obj = session.optimizer_score(cand, phase=f"{phase_prefix}_pick")
        if obj < best_obj:
            best_obj = obj
            free_best = cand
    return free_best


def _make_optuna_sampler(name: str, *, seed: int) -> optuna.samplers.BaseSampler:
    if name == "tpe":
        return TPESampler(seed=seed)
    if name == "cmaes":
        return CmaEsSampler(seed=seed, with_margin=True)
    if name == "random":
        return RandomSampler(seed=seed)
    if name == "qmc":
        return QMCSampler(seed=seed, scramble=True)
    if name == "gp":
        return GPSampler(seed=seed)
    raise ValueError(f"unsupported optuna sampler {name!r}")


def _run_optuna_sampler_strategy(
    session: FitSession,
    *,
    sampler_name: str,
    phase: str,
    refine: bool = True,
) -> FitResult:
    """Optuna global search with a named sampler, then optional L-BFGS-B refine."""
    engine = _effective_engine_policy(session.engine, session.policy)
    policy = session.policy

    def objective(trial: optuna.Trial) -> float:
        free: dict[str, float] = {}
        for name in session.free_names:
            lo, hi = session.bounds[name]
            free[name] = trial.suggest_float(
                name,
                lo,
                hi,
                log=name in LOG_SCALE_PARAMS,
            )
        return session.optimizer_score(free, phase=phase)

    study = optuna.create_study(
        direction="minimize",
        sampler=_make_optuna_sampler(
            sampler_name,
            seed=session.seed + len(session.free_names),
        ),
    )
    study.optimize(
        objective,
        n_trials=int(engine.optuna_trials or policy.optuna_trials),
        show_progress_bar=False,
        catch=(RuntimeError,),
    )
    starts: list[dict[str, float]] = []
    seen: set[tuple[float, ...]] = set()
    for trial in sorted(
        study.trials,
        key=lambda t: float(t.value if t.value is not None else 1e300),
    ):
        if trial.value is None or not math.isfinite(float(trial.value)):
            continue
        free = {name: float(trial.params[name]) for name in session.free_names}
        key = tuple(round(free[n], 12) for n in session.free_names)
        if key in seen:
            continue
        seen.add(key)
        starts.append(free)
        if len(starts) >= max(1, int(engine.refine_starts or policy.refine_starts)):
            break
    if not starts:
        starts = [_study_best_free(study, session.free_names)]
    free_best = dict(starts[0])
    if refine and int(engine.refine_starts or policy.refine_starts) > 0:
        free_best = _run_lbfgsb_refine(
            session,
            free_start=free_best,
            bounds=session.bounds,
            refine_starts=int(engine.refine_starts or policy.refine_starts),
            refine_maxiter=int(engine.refine_maxiter or policy.refine_maxiter),
            phase_prefix=f"{phase}_refine",
        )
    return session.finalize(free_best)


def run_optuna_strategy(session: FitSession, *, refine: bool = True) -> FitResult:
    """Full-space Optuna TPE followed by optional L-BFGS-B refine."""
    return _run_optuna_sampler_strategy(
        session,
        sampler_name="tpe",
        phase="optuna",
        refine=refine,
    )


def run_optuna_cmaes_strategy(
    session: FitSession,
    *,
    refine: bool = True,
) -> FitResult:
    """Full-space Optuna CMA-ES followed by optional L-BFGS-B refine."""
    return _run_optuna_sampler_strategy(
        session,
        sampler_name="cmaes",
        phase="optuna_cmaes",
        refine=refine,
    )


def run_optuna_random_strategy(
    session: FitSession,
    *,
    refine: bool = True,
) -> FitResult:
    """Full-space Optuna random search followed by optional L-BFGS-B refine."""
    return _run_optuna_sampler_strategy(
        session,
        sampler_name="random",
        phase="optuna_random",
        refine=refine,
    )


def run_optuna_qmc_strategy(
    session: FitSession,
    *,
    refine: bool = True,
) -> FitResult:
    """Full-space Optuna quasi-Monte Carlo search, then L-BFGS-B refine."""
    return _run_optuna_sampler_strategy(
        session,
        sampler_name="qmc",
        phase="optuna_qmc",
        refine=refine,
    )


def run_optuna_gp_strategy(
    session: FitSession,
    *,
    refine: bool = True,
) -> FitResult:
    """Full-space Optuna Gaussian-process BO, then L-BFGS-B refine."""
    return _run_optuna_sampler_strategy(
        session,
        sampler_name="gp",
        phase="optuna_gp",
        refine=refine,
    )


def _free_from_vector(
    session: FitSession,
    x: np.ndarray,
) -> dict[str, float]:
    return {name: float(value) for name, value in zip(session.free_names, x)}


def _run_scipy_global_strategy(
    session: FitSession,
    *,
    method: str,
    phase: str,
    refine: bool = True,
) -> FitResult:
    """SciPy global search with evaluation budget tied to ``optuna_trials``."""
    engine = _effective_engine_policy(session.engine, session.policy)
    trials = int(engine.optuna_trials or session.policy.optuna_trials)
    box = [(session.bounds[n][0], session.bounds[n][1]) for n in session.free_names]

    def vec_obj(x: np.ndarray) -> float:
        return session.optimizer_score(_free_from_vector(session, x), phase=phase)

    if method == "differential_evolution":
        popsize = max(5, len(session.free_names))
        result = differential_evolution(
            vec_obj,
            box,
            maxiter=max(1, trials // popsize),
            popsize=popsize,
            seed=session.seed,
            polish=False,
            updating="deferred",
            workers=1,
        )
    elif method == "dual_annealing":
        result = dual_annealing(
            vec_obj,
            box,
            maxfun=trials,
            seed=session.seed,
        )
    else:
        raise ValueError(f"unsupported scipy global method {method!r}")

    free_best = _free_from_vector(session, result.x)
    if refine and int(engine.refine_starts or session.policy.refine_starts) > 0:
        free_best = _run_lbfgsb_refine(
            session,
            free_start=free_best,
            bounds=session.bounds,
            refine_starts=int(engine.refine_starts or session.policy.refine_starts),
            refine_maxiter=int(engine.refine_maxiter or session.policy.refine_maxiter),
            phase_prefix=f"{phase}_refine",
        )
    return session.finalize(free_best)


def run_differential_evolution_strategy(
    session: FitSession,
    *,
    refine: bool = True,
) -> FitResult:
    """SciPy differential evolution followed by optional L-BFGS-B refine."""
    return _run_scipy_global_strategy(
        session,
        method="differential_evolution",
        phase="differential_evolution",
        refine=refine,
    )


def run_dual_annealing_strategy(
    session: FitSession,
    *,
    refine: bool = True,
) -> FitResult:
    """SciPy dual annealing followed by optional L-BFGS-B refine."""
    return _run_scipy_global_strategy(
        session,
        method="dual_annealing",
        phase="dual_annealing",
        refine=refine,
    )


def run_lbfgsb_strategy(session: FitSession) -> FitResult:
    """L-BFGS-B from geometric-mean initial guess (no global search)."""
    engine = _effective_engine_policy(session.engine, session.policy)
    free_start = _initial_free(
        free_names=session.free_names,
        bounds=session.bounds,
        init_params=session.init_params,
    )
    free_best = _run_lbfgsb_refine(
        session,
        free_start=free_start,
        bounds=session.bounds,
        refine_starts=max(1, int(engine.refine_starts or session.policy.refine_starts)),
        refine_maxiter=int(engine.refine_maxiter or session.policy.refine_maxiter),
        phase_prefix="lbfgsb",
    )
    return session.finalize(free_best)


def _optimize_stage(
    session: FitSession,
    *,
    stage: FitStage,
    state: Mapping[str, float],
    stage_policy: LossPolicy,
    maxiter: int = 40,
) -> dict[str, float]:
    curves = select_curves(session.golden, stage.curves)
    stage_bounds = {name: session.bounds[name] for name in stage.free}
    x0 = np.array([state[name] for name in stage.free], dtype=float)
    box = [(stage_bounds[n][0], stage_bounds[n][1]) for n in stage.free]

    def local_obj(x: np.ndarray) -> float:
        free = dict(state)
        for name, value in zip(stage.free, x):
            free[name] = float(value)
        return session.optimizer_score(
            free,
            phase=f"stage:{stage.stage_id}",
            policy=stage_policy,
            curves=curves,
        )

    result = minimize(
        local_obj,
        x0=x0,
        method="L-BFGS-B",
        bounds=box,
        options={"maxiter": maxiter, "ftol": 1e-6, "eps": 1e-3},
    )
    out = dict(state)
    for name, value in zip(stage.free, result.x):
        out[name] = float(value)
    return out


def run_staged_strategy(
    session: FitSession,
    profile: FitProfile,
    *,
    refine: bool = True,
) -> FitResult:
    """Design-oriented stages followed by full-grid L-BFGS-B refine."""
    engine = _effective_engine_policy(session.engine, session.policy)
    state = _initial_free(
        free_names=session.free_names,
        bounds=session.bounds,
        init_params=session.init_params,
    )
    stages = profile.stages_for_model(session.free_names)
    stage_maxiter = 40
    if int(engine.optuna_trials or session.policy.optuna_trials) <= 15:
        stage_maxiter = 10
    for stage in stages:
        stage_policy = session.policy
        if stage.loss_overrides:
            stage_policy = loss_policy_from_mapping(
                {**session.policy.to_dict(), **stage.loss_overrides}
            )
        state = _optimize_stage(
            session,
            stage=stage,
            state=state,
            stage_policy=stage_policy,
            maxiter=stage_maxiter,
        )
    if refine and int(engine.refine_starts or session.policy.refine_starts) > 0:
        state = _run_lbfgsb_refine(
            session,
            free_start=state,
            bounds=session.bounds,
            refine_starts=int(engine.refine_starts or session.policy.refine_starts),
            refine_maxiter=int(engine.refine_maxiter or session.policy.refine_maxiter),
            phase_prefix="staged_refine",
        )
    return session.finalize(state)


def _run_staged_sampler_strategy(
    session: FitSession,
    profile: FitProfile,
    *,
    strategy: str,
    sampler_name: str,
    refine: bool = True,
) -> FitResult:
    """Staged extraction, narrow-box Optuna search, then L-BFGS-B refine."""
    engine = _effective_engine_policy(session.engine, session.policy)
    state = _initial_free(
        free_names=session.free_names,
        bounds=session.bounds,
        init_params=session.init_params,
    )
    stages = profile.stages_for_model(session.free_names)
    trials = int(engine.optuna_trials or session.policy.optuna_trials)
    stage_maxiter = 10 if trials <= 15 else 40
    for stage in stages:
        stage_policy = session.policy
        if stage.loss_overrides:
            stage_policy = loss_policy_from_mapping(
                {**session.policy.to_dict(), **stage.loss_overrides}
            )
        state = _optimize_stage(
            session,
            stage=stage,
            state=state,
            stage_policy=stage_policy,
            maxiter=stage_maxiter,
        )

    if trials <= 15:
        if refine and int(engine.refine_starts or session.policy.refine_starts) > 0:
            state = _run_lbfgsb_refine(
                session,
                free_start=state,
                bounds=session.bounds,
                refine_starts=1,
                refine_maxiter=min(
                    8, int(engine.refine_maxiter or session.policy.refine_maxiter)
                ),
                phase_prefix=f"{strategy}_refine",
            )
        return session.finalize(state)

    narrow = _narrow_bounds(
        state,
        session.bounds,
        session.free_names,
        session.engine.optuna_box_fraction,
    )

    def objective(trial: optuna.Trial) -> float:
        free = dict(state)
        for name in session.free_names:
            lo, hi = narrow[name]
            free[name] = trial.suggest_float(
                name,
                lo,
                hi,
                log=name in LOG_SCALE_PARAMS,
            )
        return session.optimizer_score(free, phase=strategy)

    study = optuna.create_study(
        direction="minimize",
        sampler=_make_optuna_sampler(
            sampler_name,
            seed=session.seed + len(session.free_names) + 17,
        ),
    )
    narrow_trials = max(5, min(trials, trials // 5))
    study.optimize(
        objective,
        n_trials=narrow_trials,
        show_progress_bar=False,
        catch=(RuntimeError,),
    )
    free_best = _study_best_free(study, session.free_names)

    if refine and int(engine.refine_starts or session.policy.refine_starts) > 0:
        free_best = _run_lbfgsb_refine(
            session,
            free_start=free_best,
            bounds=session.bounds,
            refine_starts=int(engine.refine_starts or session.policy.refine_starts),
            refine_maxiter=int(engine.refine_maxiter or session.policy.refine_maxiter),
            phase_prefix=f"{strategy}_refine",
        )
    return session.finalize(free_best)


def run_staged_optuna_strategy(
    session: FitSession,
    profile: FitProfile,
    *,
    refine: bool = True,
) -> FitResult:
    """Staged extraction, narrow-box TPE, then L-BFGS-B refine."""
    return _run_staged_sampler_strategy(
        session,
        profile,
        strategy="staged_optuna",
        sampler_name="tpe",
        refine=refine,
    )


def run_staged_cmaes_strategy(
    session: FitSession,
    profile: FitProfile,
    *,
    refine: bool = True,
) -> FitResult:
    """Staged extraction, narrow-box CMA-ES, then L-BFGS-B refine."""
    return _run_staged_sampler_strategy(
        session,
        profile,
        strategy="staged_cmaes",
        sampler_name="cmaes",
        refine=refine,
    )


def run_single_strategy(
    session: FitSession,
    *,
    strategy: str,
    repo_root: Any,
    profile: FitProfile | None,
) -> FitResult:
    """Run one named strategy on a prepared session."""
    if strategy == "optuna":
        return run_optuna_strategy(session, refine=True)
    if strategy == "optuna_cmaes":
        return run_optuna_cmaes_strategy(session, refine=True)
    if strategy == "optuna_gp":
        return run_optuna_gp_strategy(session, refine=True)
    if strategy == "optuna_qmc":
        return run_optuna_qmc_strategy(session, refine=True)
    if strategy == "optuna_random":
        return run_optuna_random_strategy(session, refine=True)
    if strategy == "differential_evolution":
        return run_differential_evolution_strategy(session, refine=True)
    if strategy == "dual_annealing":
        return run_dual_annealing_strategy(session, refine=True)
    if strategy == "lbfgsb":
        return run_lbfgsb_strategy(session)
    if strategy in FIT_PROFILE_STRATEGIES:
        if profile is None:
            profile_id = session.engine.fit_profile
            if not profile_id:
                raise ValueError(
                    f"strategy={strategy!r} requires fit_engine.fit_profile"
                )
            profile = resolve_fit_profile(
                repo_root,
                profile_id=profile_id,
                model_tier=session.model.name,
                free_params=session.free_names,
            )
        if strategy == "staged":
            return run_staged_strategy(session, profile, refine=True)
        if strategy in STAGED_SAMPLER_STRATEGIES:
            return _run_staged_sampler_strategy(
                session,
                profile,
                strategy=strategy,
                sampler_name=STAGED_SAMPLER_STRATEGIES[strategy],
                refine=True,
            )
    raise ValueError(f"unsupported strategy {strategy!r}")


__all__ = [
    "FitSession",
    "run_optuna_strategy",
    "run_optuna_cmaes_strategy",
    "run_optuna_gp_strategy",
    "run_optuna_qmc_strategy",
    "run_optuna_random_strategy",
    "run_differential_evolution_strategy",
    "run_dual_annealing_strategy",
    "run_lbfgsb_strategy",
    "run_staged_strategy",
    "run_staged_optuna_strategy",
    "run_staged_cmaes_strategy",
    "run_single_strategy",
    "select_curves",
]
