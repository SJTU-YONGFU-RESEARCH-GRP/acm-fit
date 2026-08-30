"""QLAW discovery ranking, champion selection, and benchmark reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class LaneSpec:
    """One benchmark lane for QLAW discovery."""

    name: str
    role: str
    golden_config: Path
    qlaw_config: Path
    targets: tuple[str, ...]
    requires_smc: bool


@dataclass(frozen=True)
class ChampionPick:
    """Best stage row for one PDK or cross-PDK scope."""

    pdk: str | None
    stage: str
    physics_tier: str
    method: str
    weighted_err: float
    max_weighted_err: float | None = None


@dataclass(frozen=True)
class FrozenValidation:
    """Comparison of discovered champions against frozen qlaw_defaults.json."""

    ok: bool
    mismatches: tuple[str, ...]


def load_discovery_config(path: Path, repo_root: Path) -> dict[str, Any]:
    """Load ``config/qlaw_discovery.json`` and resolve lane paths."""
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = json.loads(path.read_text())
    lanes: dict[str, LaneSpec] = {}
    for name, entry in raw["lanes"].items():
        lanes[name] = LaneSpec(
            name=name,
            role=str(entry["role"]),
            golden_config=(repo_root / entry["golden_config"]).resolve(),
            qlaw_config=(repo_root / entry["qlaw_config"]).resolve(),
            targets=tuple(str(t) for t in entry["targets"]),
            requires_smc=bool(entry.get("requires_smc", False)),
        )
    raw["_lanes"] = lanes
    raw["_path"] = path.resolve()
    return raw


def mode_spec(cfg: Mapping[str, Any], mode: str) -> dict[str, Any]:
    """Return mode block; fail if unknown."""
    modes = cfg.get("modes")
    if not modes or mode not in modes:
        known = ", ".join(sorted(modes or {}))
        raise ValueError(f"unknown discovery mode {mode!r}; known: {known}")
    return dict(modes[mode])


def lane_results_dir(repo_root: Path, lane_name: str) -> Path:
    """Per-lane artifact root under ``results/qlaw_discovery/<lane>/``."""
    return repo_root / "results" / "qlaw_discovery" / lane_name


def rank_rows(rows: list[dict[str, Any]], pdk: str) -> list[dict[str, Any]]:
    """Sort rows for one PDK by ascending weighted DC objective."""
    pdk_rows = [r for r in rows if str(r["pdk"]) == pdk]
    return sorted(pdk_rows, key=lambda r: float(r["objective"]))


def select_per_pdk_champions(
    rows: list[dict[str, Any]], pdks: tuple[str, ...]
) -> dict[str, ChampionPick]:
    """Pick lowest weighted-error stage per PDK."""
    out: dict[str, ChampionPick] = {}
    for pdk in pdks:
        ranked = rank_rows(rows, pdk)
        if not ranked:
            raise ValueError(f"no ranking rows for pdk {pdk!r}")
        best = ranked[0]
        out[pdk] = ChampionPick(
            pdk=pdk,
            stage=str(best["stage"]),
            physics_tier=str(best["physics_tier"]),
            method=str(best.get("method", "")),
            weighted_err=float(best["objective"]),
        )
    return out


def select_cross_pdk_champion(
    rows: list[dict[str, Any]], pdks: tuple[str, ...]
) -> ChampionPick:
    """Pick stage minimizing max weighted error across all PDKs."""
    stages = sorted({str(r["stage"]) for r in rows})
    best_row: dict[str, Any] | None = None
    best_max = float("inf")
    for stage in stages:
        by_pdk = {str(r["pdk"]): r for r in rows if str(r["stage"]) == stage}
        if not all(pdk in by_pdk for pdk in pdks):
            continue
        max_err = max(float(by_pdk[pdk]["objective"]) for pdk in pdks)
        if max_err < best_max:
            best_max = max_err
            best_row = by_pdk[pdks[0]]
    if best_row is None:
        raise ValueError(f"no stage covers all pdks: {pdks!r}")
    return ChampionPick(
        pdk=None,
        stage=str(best_row["stage"]),
        physics_tier=str(best_row["physics_tier"]),
        method=str(best_row.get("method", "")),
        weighted_err=float(best_row["objective"]),
        max_weighted_err=best_max,
    )


def load_stages_rows(stages_json: Path) -> list[dict[str, Any]]:
    """Load ``STAGES.json`` rows from a qlaw_x run."""
    if not stages_json.is_file():
        raise FileNotFoundError(stages_json)
    payload = json.loads(stages_json.read_text())
    rows = payload.get("rows")
    if not rows:
        raise ValueError(f"no rows in {stages_json}")
    return list(rows)


def validate_against_frozen(
    *,
    per_pdk: Mapping[str, ChampionPick],
    cross: ChampionPick,
    frozen_path: Path,
) -> FrozenValidation:
    """Compare commercial-lane champions to ``config/qlaw_defaults.json``."""
    payload = json.loads(frozen_path.read_text())
    mismatches: list[str] = []
    for pdk, frozen_entry in (payload.get("defaults") or {}).items():
        if pdk not in per_pdk:
            continue
        got = per_pdk[pdk]
        want_tier = str(frozen_entry["physics_tier"])
        want_stage = str(frozen_entry["stage"])
        if got.physics_tier != want_tier or got.stage != want_stage:
            mismatches.append(
                f"{pdk}: got {got.stage}/{got.physics_tier}, "
                f"want {want_stage}/{want_tier}"
            )
    cross_frozen = payload.get("cross_pdk") or {}
    want_cross_tier = str(cross_frozen.get("physics_tier", ""))
    want_cross_stage = str(cross_frozen.get("stage", ""))
    if cross.stage != want_cross_stage or cross.physics_tier != want_cross_tier:
        mismatches.append(
            f"cross_pdk: got {cross.stage}/{cross.physics_tier}, "
            f"want {want_cross_stage}/{want_cross_tier}"
        )
    return FrozenValidation(ok=not mismatches, mismatches=tuple(mismatches))


def write_lane_report(
    *,
    path: Path,
    lane: LaneSpec,
    rows: list[dict[str, Any]],
    per_pdk: Mapping[str, ChampionPick],
    cross: ChampionPick,
    frozen: FrozenValidation | None,
    targets: tuple[str, ...] | None = None,
) -> None:
    """Write markdown summary for one lane."""
    lines = [
        f"# QLAW discovery — {lane.name}",
        "",
        lane.role,
        "",
        "## Champions",
        "",
        "| Scope | Stage | Physics tier | Weighted err |",
        "| --- | --- | --- | --- |",
    ]
    for pdk, pick in sorted(per_pdk.items()):
        lines.append(
            f"| {pdk} | `{pick.stage}` | `{pick.physics_tier}` | {pick.weighted_err:.4g} |"
        )
    cross_err = cross.max_weighted_err if cross.max_weighted_err is not None else cross.weighted_err
    lines.extend(
        [
            f"| cross-PDK | `{cross.stage}` | `{cross.physics_tier}` | {cross_err:.4g} (max) |",
            "",
            "## Top 5 per target",
            "",
        ]
    )
    report_targets = targets if targets is not None else lane.targets
    for pdk in report_targets:
        lines.append(f"### {pdk}")
        lines.append("")
        lines.append("| Rank | Stage | Tier | Weighted err |")
        lines.append("| --- | --- | --- | --- |")
        for i, row in enumerate(rank_rows(rows, pdk)[:5], start=1):
            lines.append(
                f"| {i} | `{row['stage']}` | `{row['physics_tier']}` | "
                f"{float(row['objective']):.4g} |"
            )
        lines.append("")
    if frozen is not None:
        lines.append("## Frozen validation")
        lines.append("")
        if frozen.ok:
            lines.append("Matches `config/qlaw_defaults.json`.")
        else:
            lines.append("**MISMATCH** vs `config/qlaw_defaults.json`:")
            for msg in frozen.mismatches:
                lines.append(f"- {msg}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def write_benchmark_index(
    *,
    path: Path,
    lane_reports: Mapping[str, Path],
    frozen: FrozenValidation | None,
    frozen_note: str | None = None,
) -> None:
    """Write top-level discovery benchmark index."""
    lines = [
        "# QLAW discovery benchmark",
        "",
        "End-to-end agent/skill workflow: golden → fit → rank → promote.",
        "",
        "## Lanes",
        "",
    ]
    for name, report in sorted(lane_reports.items()):
        rel = report.relative_to(path.parent) if report.is_relative_to(path.parent) else report
        lines.append(f"- **{name}** — [{report.name}]({rel.as_posix()})")
    lines.append("")
    if frozen is not None:
        lines.append("## Commercial frozen check")
        lines.append("")
        lines.append(
            "PASS — matches frozen champions."
            if frozen.ok
            else "FAIL — see commercial lane report."
        )
        lines.append("")
    elif frozen_note:
        lines.append("## Commercial frozen check")
        lines.append("")
        lines.append(frozen_note)
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def load_commercial_frozen_validation(
    discovery_root: Path, frozen_path: Path
) -> FrozenValidation | None:
    """Re-validate frozen champions from the last commercial lane SUMMARY.json."""
    summary_path = discovery_root / "commercial_pdk" / "SUMMARY.json"
    if not summary_path.is_file():
        return None
    payload = json.loads(summary_path.read_text())
    per_pdk = {
        pdk: ChampionPick(
            pdk=pdk,
            stage=str(entry["stage"]),
            physics_tier=str(entry["physics_tier"]),
            method="",
            weighted_err=float(entry["weighted_err"]),
        )
        for pdk, entry in (payload.get("per_pdk") or {}).items()
    }
    cross_raw = payload.get("cross_pdk") or {}
    cross = ChampionPick(
        pdk=None,
        stage=str(cross_raw["stage"]),
        physics_tier=str(cross_raw["physics_tier"]),
        method="",
        weighted_err=float(cross_raw.get("max_weighted_err") or 0.0),
        max_weighted_err=float(cross_raw["max_weighted_err"])
        if cross_raw.get("max_weighted_err") is not None
        else None,
    )
    return validate_against_frozen(
        per_pdk=per_pdk, cross=cross, frozen_path=frozen_path
    )


def print_discovery_status(discovery_root: Path) -> None:
    """Print lane summaries for agent triage."""
    if not discovery_root.is_dir():
        print("no discovery results yet")
        return
    for child in sorted(discovery_root.iterdir()):
        if not child.is_dir():
            continue
        summary = child / "SUMMARY.json"
        if not summary.is_file():
            print(f"{child.name}: (no SUMMARY.json)")
            continue
        payload = json.loads(summary.read_text())
        champions = ", ".join(
            f"{pdk}={entry['stage']}"
            for pdk, entry in sorted((payload.get("per_pdk") or {}).items())
        )
        cross = payload.get("cross_pdk") or {}
        print(
            f"{child.name}: targets={payload.get('targets')} "
            f"champions=[{champions}] cross={cross.get('stage')}"
        )


__all__ = [
    "ChampionPick",
    "FrozenValidation",
    "LaneSpec",
    "lane_results_dir",
    "load_commercial_frozen_validation",
    "load_discovery_config",
    "load_stages_rows",
    "mode_spec",
    "print_discovery_status",
    "rank_rows",
    "select_cross_pdk_champion",
    "select_per_pdk_champions",
    "validate_against_frozen",
    "write_benchmark_index",
    "write_lane_report",
]
