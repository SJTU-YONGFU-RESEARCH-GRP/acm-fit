"""Load circuit-suite JSON configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from acm_golden import GoldenTarget, load_golden_config


@dataclass(frozen=True)
class PdkCircuitTarget:
    """PDK section + BSIM subcircuit names for circuit golden decks."""

    name: str
    vdd: float
    ngspice_section: str
    nfet: str
    pfet: str


@dataclass(frozen=True)
class CircuitSuiteConfig:
    """Parsed circuit benchmark manifest."""

    path: Path
    raw: Mapping[str, Any]
    models: tuple[str, ...]
    pdks: tuple[str, ...]
    pdk_targets: Mapping[str, PdkCircuitTarget]
    circuits: Mapping[str, Any]
    device_roles: Mapping[str, Any]
    paper_reference_targets: Mapping[str, Any]


def _extract_bsim_model(ref_device: str) -> str:
    """Return BSIM model name from a golden ref_device line."""
    for tok in ref_device.split():
        low = tok.lower()
        if "fet" in low:
            return tok
    raise ValueError(f"cannot find BSIM model in ref_device: {ref_device!r}")


def _pdk_targets_from_golden_adornes(
    golden_cfg: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, PdkCircuitTarget]:
    """Derive per-PDK circuit targets from golden_suite_adornes targets."""
    by_base: dict[str, dict[str, GoldenTarget]] = {}
    targets = golden_cfg.get("_targets")
    if targets is None:
        raise ValueError("golden config missing _targets; call load_golden_config first")
    raw_targets = golden_cfg["targets"]
    for name, gt in targets.items():
        entry = raw_targets[name]
        base = str(entry.get("pdk_base", name.split("_")[0]))
        polarity = gt.polarity
        by_base.setdefault(base, {})[polarity] = gt

    out: dict[str, PdkCircuitTarget] = {}
    for base, pol in by_base.items():
        if "nmos" not in pol or "pmos" not in pol:
            raise ValueError(f"PDK {base!r}: need both nmos and pmos adornes golden targets")
        nmos = pol["nmos"]
        pmos = pol["pmos"]
        nfet = _extract_bsim_model(nmos.ref_device)
        pfet = _extract_bsim_model(pmos.ref_device)
        out[base] = PdkCircuitTarget(
            name=base,
            vdd=nmos.vdd,
            ngspice_section=nmos.ngspice_section,
            nfet=nfet,
            pfet=pfet,
        )
    return out


def load_circuit_suite(path: Path, repo_root: Path) -> CircuitSuiteConfig:
    """Load ``circuit_suite_adornes.json`` and companion golden PDK metadata."""
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = json.loads(path.read_text())
    golden_path = repo_root / "config/golden_suite_adornes.json"
    if not golden_path.is_file():
        raise FileNotFoundError(golden_path)
    golden_cfg = load_golden_config(golden_path, repo_root)
    golden_cfg["_path"] = str(golden_path)
    pdk_targets = _pdk_targets_from_golden_adornes(golden_cfg, repo_root)
    pdks = tuple(raw.get("pdks", pdk_targets.keys()))
    missing = [p for p in pdks if p not in pdk_targets]
    if missing:
        raise ValueError(f"circuit suite pdks missing adornes golden targets: {missing}")
    return CircuitSuiteConfig(
        path=path,
        raw=raw,
        models=tuple(raw["models"]),
        pdks=pdks,
        pdk_targets=pdk_targets,
        circuits=dict(raw["circuits"]),
        device_roles=dict(raw["device_roles"]),
        paper_reference_targets=dict(raw.get("paper_reference_targets", {})),
    )


__all__ = ["CircuitSuiteConfig", "PdkCircuitTarget", "load_circuit_suite"]
