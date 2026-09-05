"""ACM / QLAW compact-model registry for PDK eval and parameter fitting.

Naming convention (see ``PLAN.md``)
-----------------------------------
- **Physics model id** — distinct equations + own ``.va`` / ``.osdi``.
- **Fit profile** — DC parameters only (``VT0``, ``IS``, ``n``, ``sigma``;
  ``zeta`` on ``acm5``). Non-DC params use VA defaults.

Generation-6 ``qlaw*`` tiers are registered from ``config/acm_tier_spec.json``
(charge × transport matrix). Frozen champions are production; explorers
``acm_x`` / ``qlaw_x`` stay experimental.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from acm.opt.tiers import load_tier_spec

_NMOS = {"type": 1}


@dataclass(frozen=True)
class ModelSpec:
    """Describes one ACM / QLAW compact-model family used in benchmarks."""

    name: str
    va_path: Path
    osdi_path: Path
    module_name: str
    spice_model: str
    free_params: tuple[str, ...]
    instance_fixed: Mapping[str, float | int]
    supports_zeta: bool
    experimental: bool = False
    stage: str | None = None
    doc_path: Path | None = None
    physics_tier: str | None = None


def _spice_model_name(module: str) -> str:
    """Derive a SPICE model name from the Verilog-A module id."""
    name = module[4:] if module.startswith("mos_") else module
    return name.upper()


def _tier_model(
    repo_root: Path,
    *,
    name: str,
    tier_id: str,
    spice_model: str | None = None,
    doc_path: Path | None = None,
    experimental: bool = False,
    stage: str | None = None,
    free_params: tuple[str, ...] | None = None,
    supports_zeta: bool | None = None,
    instance_fixed: Mapping[str, float | int] | None = None,
) -> ModelSpec:
    """Build a ModelSpec from ``config/acm_tier_spec.json``."""
    tiers = load_tier_spec(repo_root)
    if tier_id not in tiers:
        raise ValueError(f"unknown physics tier {tier_id!r}")
    tier = tiers[tier_id]
    if tier.va_path is None or tier.osdi_path is None:
        raise ValueError(f"tier {tier_id!r} has no va/osdi path in tier spec")
    params = free_params if free_params is not None else tier.dc_fit_params
    zeta = supports_zeta if supports_zeta is not None else ("zeta" in params)
    fixed = instance_fixed if instance_fixed is not None else (
        _NMOS if tier.generation in (4, 6) else {}
    )
    doc = doc_path if doc_path is not None else tier.doc_path
    spice = spice_model if spice_model is not None else _spice_model_name(tier.module)
    return ModelSpec(
        name=name,
        va_path=tier.va_path,
        osdi_path=tier.osdi_path,
        module_name=tier.module,
        spice_model=spice,
        free_params=params,
        instance_fixed=fixed,
        supports_zeta=zeta,
        experimental=experimental,
        stage=stage,
        doc_path=doc,
        physics_tier=tier_id,
    )


_GEN4_SPICE: dict[str, str] = {
    "acm4": "ACM4",
}
_GEN5_SPICE: dict[str, str] = {
    "acm5": "NMOS_ACM",
}


def _register_tier(
    repo_root: Path,
    out: dict[str, ModelSpec],
    *,
    tier_id: str,
    experimental: bool = False,
    stage: str | None = None,
    spice_model: str | None = None,
    doc_path: Path | None = None,
) -> None:
    """Register one physics tier when its Verilog-A source is present."""
    tiers = load_tier_spec(repo_root)
    tier = tiers[tier_id]
    if tier.va_path is None or tier.osdi_path is None:
        raise ValueError(f"tier {tier_id!r} has no va/osdi path in tier spec")
    if not tier.va_path.is_file():
        return
    if tier_id in out:
        raise ValueError(f"duplicate registry id from tier spec: {tier_id!r}")
    spice = spice_model
    if spice is None:
        if tier_id in _GEN4_SPICE:
            spice = _GEN4_SPICE[tier_id]
        elif tier_id in _GEN5_SPICE:
            spice = _GEN5_SPICE[tier_id]
        else:
            spice = _spice_model_name(tier.module)
    out[tier_id] = _tier_model(
        repo_root,
        name=tier_id,
        tier_id=tier_id,
        spice_model=spice,
        doc_path=doc_path,
        experimental=experimental or tier.status == "experimental",
        stage=stage,
    )


def default_models(repo_root: Path) -> dict[str, ModelSpec]:
    """Return the default model registry keyed by model name."""
    tiers = load_tier_spec(repo_root)
    out: dict[str, ModelSpec] = {}
    for tier_id, tier in sorted(tiers.items()):
        if tier.generation not in (4, 5, 6):
            continue
        _register_tier(
            repo_root,
            out,
            tier_id=tier_id,
            experimental=tier.status == "experimental",
        )
    if not out:
        raise ValueError(
            "no compact models registered; add tiers with Verilog-A under models/"
        )
    return out


def resolve_models(
    repo_root: Path,
    names: tuple[str, ...] | None = None,
) -> list[ModelSpec]:
    """Resolve requested model names against the registry."""
    registry = default_models(repo_root)
    selected = names if names is not None else tuple(registry.keys())
    missing = [name for name in selected if name not in registry]
    if missing:
        known = ", ".join(sorted(registry))
        raise ValueError(f"unknown model(s) {missing!r}; known: {known}")
    return [registry[name] for name in selected]


def _polarity_wrapper_paths(
    base: ModelSpec,
    polarity: str,
) -> tuple[Path, Path, str, str]:
    """Resolve NMOS_/PMOS_ VA wrappers for CMOS-capable tiers."""
    va = base.va_path
    stem = va.name
    parent = va.parent
    if stem.startswith("NMOS_"):
        nmos_va = va
        pmos_va = parent / f"PMOS_{stem[5:]}"
        mod_tail = base.module_name[5:] if base.module_name.startswith("nmos_") else base.module_name
        nmos_mod = base.module_name
        pmos_mod = f"pmos_{mod_tail}"
        nmos_spice = base.spice_model
        pmos_spice = (
            f"PMOS_{base.spice_model[5:]}"
            if base.spice_model.startswith("NMOS_")
            else f"PMOS_{base.spice_model}"
        )
    elif stem.startswith("MOS_"):
        tail = stem[4:]
        nmos_va = parent / f"NMOS_{tail}"
        pmos_va = parent / f"PMOS_{tail}"
        mod_tail = base.module_name[4:] if base.module_name.startswith("mos_") else base.module_name
        nmos_mod = f"nmos_{mod_tail}"
        pmos_mod = f"pmos_{mod_tail}"
        nmos_spice = f"NMOS_{base.spice_model}"
        pmos_spice = f"PMOS_{base.spice_model}"
    else:
        raise ValueError(f"unsupported VA name for polarity resolve: {va}")
    if polarity == "nmos":
        sel_va, sel_mod, sel_spice = nmos_va, nmos_mod, nmos_spice
    else:
        sel_va, sel_mod, sel_spice = pmos_va, pmos_mod, pmos_spice
    if not sel_va.is_file():
        raise FileNotFoundError(f"missing polarity VA wrapper: {sel_va}")
    return sel_va, sel_va.with_suffix(".osdi"), sel_mod, sel_spice


def resolve_polarity_model(
    repo_root: Path,
    name: str,
    polarity: str,
) -> ModelSpec:
    """Return a :class:`ModelSpec` configured for NMOS or PMOS simulation."""
    if polarity not in {"nmos", "pmos"}:
        raise ValueError(f"polarity must be nmos or pmos, got {polarity!r}")
    base = default_models(repo_root)[name]
    try:
        va, osdi, module, spice = _polarity_wrapper_paths(base, polarity)
    except (FileNotFoundError, ValueError):
        if polarity == "pmos" and int(base.instance_fixed.get("type", 0)) == 1:
            return replace(base, instance_fixed={"type": -1})
        return base
    return replace(
        base,
        va_path=va,
        osdi_path=osdi,
        module_name=module,
        spice_model=spice,
        instance_fixed={},
    )


def production_models(repo_root: Path) -> list[ModelSpec]:
    """Return non-experimental registry entries (excludes explorers / qlaw*)."""
    return [m for m in default_models(repo_root).values() if not m.experimental]


__all__ = [
    "ModelSpec",
    "default_models",
    "resolve_models",
    "resolve_polarity_model",
    "production_models",
]
