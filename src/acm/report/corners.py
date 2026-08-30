"""Corner-wise fit summaries for golden pipeline results."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


def _split_target_id(target: str) -> tuple[str, str | None]:
    """Return ``(base_pdk, corner)`` from a golden target id."""
    if "_" not in target:
        return target, None
    base, corner = target.rsplit("_", 1)
    if base in {"gf180mcu", "sky130"} or base.startswith("ptm"):
        return base, corner
    return target, None


def _load_cards(model_dir: Path) -> list[dict[str, Any]]:
    fit_dir = model_dir / "fit"
    if not fit_dir.is_dir():
        return []
    cards: list[dict[str, Any]] = []
    for path in sorted(fit_dir.glob("*.json")):
        if path.name in {"fit_summary.json"} or path.name.startswith("_"):
            continue
        payload = json.loads(path.read_text())
        if "parameters" not in payload:
            continue
        cards.append(payload)
    return cards


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return lines


def write_corner_report(
    *,
    results_dir: Path,
    model: str = "acm5",
    output: Path | None = None,
) -> Path:
    """Write ``CORNER_REPORT.md`` summarizing per-corner fitted DC parameters."""
    model_dir = results_dir / model
    cards = _load_cards(model_dir)
    if not cards:
        raise FileNotFoundError(f"no fitted cards under {model_dir / 'fit'}")

    by_base: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        target = str(card["pdk"])
        base = card.get("base_pdk")
        corner = card.get("corner")
        if base is None or corner is None:
            base, corner = _split_target_id(target)
        if corner is None:
            continue
        by_base.setdefault(str(base), []).append({**card, "corner": corner})

    if not by_base:
        raise ValueError(
            f"no corner targets found in {model_dir / 'fit'}; "
            "use golden_suite with a corners block"
        )

    out_path = output or (results_dir / "CORNER_REPORT.md")
    lines = [
        "# Corner fit report",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        f"Model: `{model}`",
        "",
    ]

    param_names: list[str] = []
    for group in by_base.values():
        for card in group:
            for key in card.get("parameters", {}):
                if key not in param_names and key in {"VT0", "IS", "n", "sigma", "zeta"}:
                    param_names.append(key)
    if not param_names:
        raise ValueError("fitted cards contain no DC parameters")

    for base_pdk in sorted(by_base):
        group = sorted(by_base[base_pdk], key=lambda c: str(c["corner"]))
        lines.extend([f"## {base_pdk}", ""])
        rows: list[list[Any]] = []
        for card in group:
            params: Mapping[str, Any] = card["parameters"]
            row: list[Any] = [card["corner"], f"{card['weighted_error']:.4g}"]
            for name in param_names:
                val = params.get(name)
                if name == "VT0":
                    row.append(f"{float(val) * 1e3:.2f} mV" if val is not None else "—")
                elif name == "IS":
                    row.append(f"{float(val) * 1e9:.2f} nA" if val is not None else "—")
                elif name in {"n", "sigma", "zeta"}:
                    row.append(f"{float(val):.4g}" if val is not None else "—")
                else:
                    row.append(val)
            rows.append(row)
        headers = ["Corner", "Weighted err", *param_names]
        lines.extend(_md_table(headers, rows))
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n")
    return out_path


__all__ = ["write_corner_report"]
