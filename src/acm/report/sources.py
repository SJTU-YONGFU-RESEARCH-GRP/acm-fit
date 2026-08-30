"""Discover golden input metadata for regression reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"expected object in {path}")
    return payload


def discover_input_sources(
    results_dir: Path,
    targets: list[str],
) -> list[dict[str, Any]]:
    """Load per-target golden metadata from ``results/golden/<target>/meta.json``."""
    golden_root = results_dir / "golden"
    rows: list[dict[str, Any]] = []
    for target in sorted(targets):
        meta_path = golden_root / target / "meta.json"
        if not meta_path.is_file():
            rows.append(
                {
                    "target": target,
                    "source": "unknown",
                    "vdd": "—",
                    "width_m": "—",
                    "length_m": "—",
                    "polarity": "—",
                    "corner": "—",
                    "n_curves": "—",
                }
            )
            continue
        meta = _load_meta(meta_path)
        vds_list = meta.get("vds_list", [])
        rows.append(
            {
                "target": target,
                "source": str(meta.get("source", "user_supplied")),
                "vdd": meta.get("vdd"),
                "width_m": meta.get("width_m"),
                "length_m": meta.get("length_m"),
                "polarity": str(meta.get("polarity", "nmos")),
                "corner": meta.get("corner") or "—",
                "base_pdk": meta.get("base_pdk") or "—",
                "n_curves": len(vds_list) if isinstance(vds_list, list) else "—",
            }
        )
    return rows


def report_capabilities(
    *,
    sources: list[dict[str, Any]],
    eval_rows: list[dict[str, Any]],
) -> dict[str, bool]:
    """Return which report sections apply for this results tree."""
    has_eval_refs = bool(eval_rows)
    user_only = bool(sources) and all(
        str(row.get("source", "")).startswith("user_supplied") for row in sources
    )
    return {
        "fit_dc": bool(sources),
        "eval_waveforms": has_eval_refs,
        "user_supplied_only": user_only and not has_eval_refs,
    }


__all__ = ["discover_input_sources", "report_capabilities"]
