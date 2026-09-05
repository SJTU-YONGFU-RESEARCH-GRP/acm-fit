"""Fit-engine policy: which search strategy drives DC parameter extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

SUPPORTED_STRATEGIES: tuple[str, ...] = (
    "optuna",
    "optuna_cmaes",
    "optuna_gp",
    "optuna_qmc",
    "optuna_random",
    "differential_evolution",
    "dual_annealing",
    "lbfgsb",
    "staged",
    "staged_optuna",
    "staged_cmaes",
    "benchmark",
)

BENCHMARKABLE_STRATEGIES: frozenset[str] = frozenset(
    {
        "optuna",
        "optuna_cmaes",
        "optuna_gp",
        "optuna_qmc",
        "optuna_random",
        "differential_evolution",
        "dual_annealing",
        "lbfgsb",
        "staged",
        "staged_optuna",
        "staged_cmaes",
    }
)

FIT_PROFILE_STRATEGIES: frozenset[str] = frozenset(
    {"staged", "staged_optuna", "staged_cmaes"}
)

STAGED_SAMPLER_STRATEGIES: dict[str, str] = {
    "staged_optuna": "tpe",
    "staged_cmaes": "cmaes",
}

# Backward-compatible alias used by narrow-box hybrid helpers.
STAGED_STRATEGIES: frozenset[str] = frozenset(FIT_PROFILE_STRATEGIES)


@dataclass(frozen=True)
class WarmStartPolicy:
    """Optional warm-start from a parent process corner."""

    mode: str
    corner_order: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        if self.mode != "parent_corner":
            raise ValueError(
                f"unsupported warm_start.mode {self.mode!r}; "
                "known: parent_corner"
            )
        if not self.corner_order:
            raise ValueError("warm_start.corner_order must be non-empty")


@dataclass(frozen=True)
class FitEnginePolicy:
    """Search strategy and staged-fit options (orthogonal to ``LossPolicy``)."""

    strategy: str = "optuna"
    strategies: tuple[str, ...] = (
        "optuna",
        "optuna_cmaes",
        "optuna_gp",
        "optuna_qmc",
        "optuna_random",
        "differential_evolution",
        "dual_annealing",
        "lbfgsb",
        "staged",
        "staged_optuna",
        "staged_cmaes",
    )
    fit_profile: str | None = "acm5_staged"
    optuna_trials: int | None = None
    refine_starts: int | None = None
    refine_maxiter: int | None = None
    optuna_box_fraction: float = 0.2
    warm_start: WarmStartPolicy | None = None

    def __post_init__(self) -> None:
        if self.strategy not in SUPPORTED_STRATEGIES:
            raise ValueError(
                f"unsupported fit_engine.strategy {self.strategy!r}; "
                f"known={SUPPORTED_STRATEGIES}"
            )
        if self.optuna_box_fraction <= 0.0 or self.optuna_box_fraction >= 1.0:
            raise ValueError(
                "optuna_box_fraction must be in (0, 1), "
                f"got {self.optuna_box_fraction}"
            )
        for name in self.strategies:
            if name not in BENCHMARKABLE_STRATEGIES:
                known = ", ".join(sorted(BENCHMARKABLE_STRATEGIES))
                raise ValueError(
                    f"invalid fit_engine.strategies entry {name!r}; "
                    f"known: {known}"
                )
        if self.strategy in FIT_PROFILE_STRATEGIES and not self.fit_profile:
            raise ValueError(
                f"fit_engine.strategy={self.strategy!r} requires fit_profile"
            )
        if self.strategy == "benchmark" and not self.strategies:
            raise ValueError("fit_engine.strategy=benchmark requires strategies")


def fit_engine_from_mapping(
    raw: Mapping[str, Any] | None,
) -> FitEnginePolicy:
    """Parse ``fit_engine`` block from a golden-suite JSON config."""
    if raw is None:
        return FitEnginePolicy()
    strategy = str(raw.get("strategy", "optuna"))
    strategies_raw = raw.get("strategies")
    if strategies_raw is None:
        strategies = FitEnginePolicy().strategies
    else:
        if not isinstance(strategies_raw, list) or not strategies_raw:
            raise ValueError("fit_engine.strategies must be a non-empty list")
        strategies = tuple(str(s) for s in strategies_raw)
    fit_profile = raw.get("fit_profile")
    if fit_profile is not None:
        fit_profile = str(fit_profile)
    warm_start: WarmStartPolicy | None = None
    ws_raw = raw.get("warm_start")
    if ws_raw is not None:
        if not isinstance(ws_raw, Mapping):
            raise ValueError("fit_engine.warm_start must be an object")
        mode = str(ws_raw.get("mode", ""))
        order_raw = ws_raw.get("corner_order")
        if not isinstance(order_raw, Mapping):
            raise ValueError(
                "fit_engine.warm_start.corner_order must be an object "
                "mapping base_pdk → corner list"
            )
        corner_order: dict[str, tuple[str, ...]] = {}
        for base_pdk, corners in order_raw.items():
            if not isinstance(corners, list) or not corners:
                raise ValueError(
                    f"warm_start.corner_order[{base_pdk!r}] must be a "
                    "non-empty list"
                )
            corner_order[str(base_pdk)] = tuple(str(c) for c in corners)
        warm_start = WarmStartPolicy(mode=mode, corner_order=corner_order)
    optuna_trials = raw.get("optuna_trials")
    refine_starts = raw.get("refine_starts")
    refine_maxiter = raw.get("refine_maxiter")
    box_frac = float(raw.get("optuna_box_fraction", 0.2))
    return FitEnginePolicy(
        strategy=strategy,
        strategies=strategies,
        fit_profile=fit_profile,
        optuna_trials=int(optuna_trials) if optuna_trials is not None else None,
        refine_starts=int(refine_starts) if refine_starts is not None else None,
        refine_maxiter=int(refine_maxiter) if refine_maxiter is not None else None,
        optuna_box_fraction=box_frac,
        warm_start=warm_start,
    )


def resolve_parent_target_name(
    *,
    base_pdk: str | None,
    corner: str | None,
    warm_start: WarmStartPolicy | None,
) -> str | None:
    """Return parent golden target name for corner warm-start, if any."""
    if warm_start is None or base_pdk is None or corner is None:
        return None
    order = warm_start.corner_order.get(base_pdk)
    if not order or corner not in order:
        return None
    idx = order.index(corner)
    if idx == 0:
        return None
    parent_corner = order[idx - 1]
    return f"{base_pdk}_{parent_corner}"


def fit_job_waves(
    target_names: tuple[str, ...],
    *,
    golden_dir: Any,
    warm_start: WarmStartPolicy | None,
    load_golden_device: Any,
) -> tuple[tuple[str, ...], ...]:
    """Partition fit targets into waves respecting parent-corner warm-start deps."""
    if warm_start is None:
        return (target_names,)
    remaining = set(target_names)
    waves: list[tuple[str, ...]] = []
    while remaining:
        wave: list[str] = []
        for name in sorted(remaining):
            golden = load_golden_device(golden_dir / name)
            parent = resolve_parent_target_name(
                base_pdk=golden.base_pdk,
                corner=golden.corner,
                warm_start=warm_start,
            )
            if parent is None or parent not in remaining:
                wave.append(name)
        if not wave:
            raise RuntimeError(
                "cyclic warm_start dependency among targets: "
                f"{sorted(remaining)}"
            )
        waves.append(tuple(wave))
        for name in wave:
            remaining.remove(name)
    return tuple(waves)


__all__ = [
    "SUPPORTED_STRATEGIES",
    "BENCHMARKABLE_STRATEGIES",
    "FIT_PROFILE_STRATEGIES",
    "STAGED_SAMPLER_STRATEGIES",
    "STAGED_STRATEGIES",
    "FitEnginePolicy",
    "WarmStartPolicy",
    "fit_engine_from_mapping",
    "resolve_parent_target_name",
    "fit_job_waves",
]
