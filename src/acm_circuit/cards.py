"""Load fitted ACM cards for circuit benchmarks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from acm_opt.params import fill_missing_free_params
from acm_opt.models import ModelSpec, resolve_polarity_model


def device_card_key(pdk: str, polarity: str, width_m: float, length_m: float) -> str:
    """Canonical fit-card stem for one device geometry."""
    w_um = int(round(width_m * 1e6))
    l_um = int(round(length_m * 1e6))
    return f"{pdk}_{polarity}_{w_um}u{l_um}u"


def load_device_card(
    *,
    results_dir: Path,
    model: ModelSpec,
    repo_root: Path,
    model_name: str,
    pdk: str,
    polarity: str,
    width_m: float,
    length_m: float,
) -> dict[str, Any]:
    """Load a fitted card JSON for one device role."""
    key = device_card_key(pdk, polarity, width_m, length_m)
    path = results_dir / model_name / "fit" / f"{key}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"missing fit card {path}; run scripts/run_adornes_golden_fit.py first"
        )
    data = json.loads(path.read_text())
    pol = resolve_polarity_model(repo_root, model_name, polarity)
    params = fill_missing_free_params(pol, data["parameters"])
    params["W"] = float(data["parameters"].get("W", width_m))
    params["L"] = float(data["parameters"].get("L", length_m))
    for key, value in pol.instance_fixed.items():
        params[key] = float(value)
    if not pol.instance_fixed:
        params.pop("type", None)
    return {
        "path": path,
        "parameters": params,
        "polarity": polarity,
        "model_spec": pol,
        "weighted_error": float(data["weighted_error"]),
    }


__all__ = ["device_card_key", "load_device_card"]
