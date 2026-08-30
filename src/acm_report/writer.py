"""Aggregate regression artifacts into SUMMARY.md and per-model REPORT.md."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from acm_report.plots import write_bench_waveform_plots, write_eval_overlay_plots
from acm_report.sources import discover_input_sources, report_capabilities

_RESERVED = frozenset({"golden", "ablation"})


def _load_json(path: Path) -> Any:
    """Load JSON file; fail if missing."""
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def discover_model_dirs(results_dir: Path) -> list[Path]:
    """Return ``results/<model>/`` dirs that contain a ``fit/`` tree."""
    if not results_dir.is_dir():
        raise FileNotFoundError(results_dir)
    return sorted(
        path
        for path in results_dir.iterdir()
        if path.is_dir()
        and path.name not in _RESERVED
        and not path.name.startswith(".")
        and (path / "fit").is_dir()
    )


def discover_fitted_cards(model_dir: Path) -> list[dict[str, Any]]:
    """Load fitted cards from ``<model>/fit/<pdk>.json``."""
    fit_dir = model_dir / "fit"
    if not fit_dir.is_dir():
        return []
    cards: list[dict[str, Any]] = []
    for path in sorted(fit_dir.glob("*.json")):
        if path.name.startswith("_") or path.name == "fit_summary.json":
            continue
        payload = _load_json(path)
        required = ("parameters", "model", "pdk", "weighted_error", "vdd")
        missing = [k for k in required if k not in payload]
        if missing:
            raise ValueError(f"{path}: missing fields {missing}")
        if payload["model"] != model_dir.name:
            raise ValueError(
                f"{path}: model {payload['model']!r} != directory {model_dir.name!r}"
            )
        if payload["pdk"] != path.stem:
            raise ValueError(
                f"{path}: pdk {payload['pdk']!r} != filename stem {path.stem!r}"
            )
        cards.append(payload)
    return cards


def discover_bench_rows(model_dir: Path) -> list[dict[str, Any]]:
    """Load predict bench rows from ``<model>/benches/summary.json``."""
    summary = model_dir / "benches" / "summary.json"
    if not summary.is_file():
        return []
    rows = _load_json(summary)
    if not isinstance(rows, list):
        raise ValueError(f"expected list in {summary}")
    for row in rows:
        for key in ("pdk", "model", "simulator", "analysis", "ok"):
            if key not in row:
                raise ValueError(f"{summary}: row missing {key!r}")
        if row["model"] != model_dir.name:
            raise ValueError(
                f"{summary}: model {row['model']!r} != directory {model_dir.name!r}"
            )
    return rows


def discover_eval_rows(model_dir: Path) -> list[dict[str, Any]]:
    """Load eval rows from ``<model>/eval/summary.json``."""
    summary = model_dir / "eval" / "summary.json"
    if not summary.is_file():
        return []
    payload = _load_json(summary)
    if not isinstance(payload, dict) or "results" not in payload:
        raise ValueError(f"expected object with 'results' in {summary}")
    rows = payload["results"]
    if not isinstance(rows, list):
        raise ValueError(f"expected list results in {summary}")
    for row in rows:
        for key in ("pdk", "model", "simulator", "analysis", "status"):
            if key not in row:
                raise ValueError(f"{summary}: row missing {key!r}")
        if row["model"] != model_dir.name:
            raise ValueError(
                f"{summary}: model {row['model']!r} != directory {model_dir.name!r}"
            )
    return rows


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    """Render a GitHub-flavored markdown table."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return lines


def _status_ok(row: Mapping[str, Any]) -> bool:
    """Return True if a predict/eval row is successful."""
    if "ok" in row:
        return bool(row["ok"])
    return str(row["status"]).lower() == "ok"


def _fmt(value: float, *, digits: int = 4) -> str:
    """Format a float for markdown tables."""
    return f"{float(value):.{digits}g}"


def _eval_accuracy(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return ``(metric_name, primary, secondary)`` accuracy cells for one eval row.

    Raises:
        ValueError: If status is ok but analysis metrics are missing/unknown.
    """
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping) or not metrics:
        if _status_ok(row):
            raise ValueError(
                f"eval row missing metrics: {row['pdk']}/{row['model']}/"
                f"{row['simulator']}/{row['analysis']}"
            )
        return "—", "—", "—"
    if "rmse_linear" in metrics and "rmse_log" in metrics:
        return (
            "Id RMSE lin/log",
            _fmt(float(metrics["rmse_linear"])),
            _fmt(float(metrics["rmse_log"])),
        )
    if "rmse_vm" in metrics:
        return ("Vmag RMSE", _fmt(float(metrics["rmse_vm"])), "—")
    if "rmse_onoise" in metrics:
        return ("onoise RMSE", _fmt(float(metrics["rmse_onoise"])), "—")
    raise ValueError(
        f"unsupported eval metrics keys {sorted(metrics)} for "
        f"{row['pdk']}/{row['analysis']}"
    )


def _eval_table_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    include_model: bool,
) -> list[list[Any]]:
    """Build eval table body rows with accuracy + resource columns."""
    out: list[list[Any]] = []
    for row in sorted(
        rows,
        key=lambda x: (
            x["pdk"],
            x.get("model", ""),
            x["simulator"],
            x["analysis"],
        ),
    ):
        metric_name, primary, secondary = _eval_accuracy(row)
        cells: list[Any] = [row["pdk"]]
        if include_model:
            cells.append(row["model"])
        cells.extend(
            [
                row["simulator"],
                row["analysis"],
                row["status"],
                metric_name,
                primary,
                secondary,
                row["runtime_s"],
                row["peak_rss_kb"],
            ]
        )
        out.append(cells)
    return out


def _fmt_geom(value: Any) -> str:
    """Format geometry fields for markdown tables."""
    if value == "—" or value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3g}"
    return str(value)


def _source_label(source: str) -> str:
    """Human-readable label for golden ``meta.json`` source."""
    labels = {
        "pdk_bsim_ngspice": "PDK BSIM (ngspice)",
        "ptm_bsim_ngspice": "PTM BSIM (ngspice)",
        "user_supplied": "User Id–Vg CSV",
        "user_supplied_example": "Bundled example CSV",
    }
    return labels.get(source, source)


def write_regression_reports(
    *,
    repo_root: Path,
    results_dir: Path | None = None,
) -> dict[str, Path]:
    """Write ``results/SUMMARY.md`` and ``results/<model>/REPORT.md``.

    Layout::

        results/golden/<pdk>/
        results/<model>/fit/<pdk>.json
        results/<model>/benches/<pdk>/...
        results/<model>/eval/<pdk>/...
    """
    _ = repo_root
    results_dir = (results_dir or Path("results")).resolve()

    model_dirs = {path.name: path for path in discover_model_dirs(results_dir)}
    cards: list[dict[str, Any]] = []
    predict_rows: list[dict[str, Any]] = []
    eval_rows: list[dict[str, Any]] = []

    for model_dir in model_dirs.values():
        cards.extend(discover_fitted_cards(model_dir))
        predict_rows.extend(discover_bench_rows(model_dir))
        eval_rows.extend(discover_eval_rows(model_dir))

    models = sorted(model_dirs)
    if not models:
        raise FileNotFoundError(
            f"no model directories under {results_dir} "
            f"(expected results/<model>/fit|benches|eval)"
        )

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    outputs: dict[str, Path] = {}
    targets = sorted({str(c["pdk"]) for c in cards})
    sources = discover_input_sources(results_dir, targets)
    capabilities = report_capabilities(sources=sources, eval_rows=eval_rows)

    for model in models:
        model_dir = model_dirs[model]
        model_eval = [r for r in eval_rows if r["model"] == model]
        model_predict = [r for r in predict_rows if r["model"] == model]
        ref_label = "BSIM golden" if capabilities["eval_waveforms"] else "Reference"
        write_eval_overlay_plots(
            results_dir=results_dir,
            model=model,
            eval_rows=model_eval,
            ref_label=ref_label,
        )
        write_bench_waveform_plots(
            results_dir=results_dir,
            model=model,
            predict_rows=model_predict,
        )

    for model in models:
        model_dir = model_dirs[model]
        report_path = model_dir / "REPORT.md"
        report_path.write_text(
            "\n".join(
                _build_model_report(
                    model=model,
                    cards=[c for c in cards if c["model"] == model],
                    predict_rows=[r for r in predict_rows if r["model"] == model],
                    eval_rows=[r for r in eval_rows if r["model"] == model],
                    fit_dir=model_dir / "fit",
                    report_dir=model_dir,
                    stamp=stamp,
                    sources=[s for s in sources if s["target"] in {c["pdk"] for c in cards if c["model"] == model}],
                    capabilities=capabilities,
                )
            )
            + "\n"
        )
        outputs[model] = report_path

    summary_path = results_dir / "SUMMARY.md"
    summary_path.write_text(
        "\n".join(
            _build_summary(
                models=models,
                cards=cards,
                predict_rows=predict_rows,
                eval_rows=eval_rows,
                stamp=stamp,
                results_dir=results_dir,
                sources=sources,
                capabilities=capabilities,
            )
        )
        + "\n"
    )
    outputs["summary"] = summary_path
    return outputs


def _build_summary(
    *,
    models: Sequence[str],
    cards: Sequence[Mapping[str, Any]],
    predict_rows: Sequence[Mapping[str, Any]],
    eval_rows: Sequence[Mapping[str, Any]],
    stamp: str,
    results_dir: Path,
    sources: Sequence[Mapping[str, Any]],
    capabilities: Mapping[str, bool],
) -> list[str]:
    """Compose overall SUMMARY.md body."""
    pred_ok = sum(1 for r in predict_rows if _status_ok(r))
    pred_fail = len(predict_rows) - pred_ok
    eval_ok = sum(1 for r in eval_rows if _status_ok(r))
    eval_fail = len(eval_rows) - eval_ok

    if capabilities.get("user_supplied_only"):
        fit_heading = "Golden I-V fit (ACM vs user-supplied Id–Vg)"
        fit_blurb = "Parameter extraction accuracy against user-supplied multi-VDS Id–Vg tables."
        eval_blurb = "_Eval suite not run (no BSIM reference waveforms for user CSV input)._"
    elif capabilities.get("eval_waveforms"):
        fit_heading = "Golden I-V fit (ACM vs PDK BSIM Id–Vg)"
        fit_blurb = "Parameter extraction accuracy against golden multi-VDS Id–Vg tables."
        eval_blurb = (
            "Golden waveforms are captured once from PDK BSIM in **ngspice**. "
            "ACM-only runs on each simulator are scored with RMSE vs that golden. "
            "**Runtime / peak RSS** are ACM-only (not a dual-DUT netlist)."
        )
    else:
        fit_heading = "Golden I-V fit"
        fit_blurb = "Parameter extraction accuracy against golden multi-VDS Id–Vg tables."
        eval_blurb = "_Eval suite not run._"

    lines: list[str] = [
        "# Regression SUMMARY",
        "",
        f"_Generated {stamp}_",
        "",
        "## What each section measures",
        "",
        "| Section | Compared to reference? | Accuracy | Runtime / memory |",
        "| --- | --- | --- | --- |",
        "| Input sources | — | Dataset provenance (PDK, user CSV, …) | Geometry + VDD |",
        "| Golden I-V fit | Yes (multi-VDS Id–Vg) | Weighted / linear / log RMSE of Id | Fit wall time + Optuna evals |",
        "| Predict benches | No reference device | ACM-only waveforms (DC/AC/noise/temp/tran) | Per-sim ACM wall time + peak RSS |",
        "| Eval suite | Yes when BSIM refs exist | ACM vs golden RMSE (DC/AC/noise/temp/tran) | ACM-only wall time + peak RSS |",
        "",
        "## Status",
        "",
        f"- Models: {', '.join(f'`{m}`' for m in models)}",
        f"- Fitted cards: **{len(cards)}**",
        f"- Predict benches: **{pred_ok} ok** / **{pred_fail} fail** "
        f"(of {len(predict_rows)})",
    ]
    if eval_rows:
        lines.append(
            f"- Eval suite (ACM vs reference golden): **{eval_ok} ok** / "
            f"**{eval_fail} fail** (of {len(eval_rows)})"
        )
    else:
        lines.append("- Eval suite: **not run** (fit-only or user CSV input)")

    if sources:
        lines.extend(
            [
                "",
                "## Input sources",
                "",
                "Golden fit targets and where their Id–Vg reference curves came from.",
                "",
            ]
        )
        lines.extend(
            _md_table(
                [
                    "Target",
                    "Source",
                    "VDD (V)",
                    "W (m)",
                    "L (m)",
                    "Polarity",
                    "Corner",
                    "# VDS curves",
                ],
                [
                    [
                        row["target"],
                        _source_label(str(row["source"])),
                        _fmt_geom(row["vdd"]),
                        _fmt_geom(row["width_m"]),
                        _fmt_geom(row["length_m"]),
                        row["polarity"],
                        row["corner"],
                        row["n_curves"],
                    ]
                    for row in sources
                ],
            )
        )

    lines.extend(
        [
            "",
            "## Layout",
            "",
            "```",
            "results/",
            "  SUMMARY.md",
            "  golden/<pdk>/",
            "    meta.json + idvg_vds_*.csv",
            "    ref/<analysis>/ref.csv   # eval BSIM golden (when available)",
            "  <model>/",
            "    REPORT.md",
            "    fit/<pdk>.json",
            "    fit/<pdk>_idvg_fit.png",
            "    plots/<pdk>/eval_<analysis>.png",
            "    benches/<pdk>/<sim>/<analysis>/",
            "    eval/<pdk>/<sim>/<analysis>/acm.csv",
            "```",
            "",
            "## Model reports",
            "",
        ]
    )
    for model in models:
        lines.append(f"- [`{model}`]({model}/REPORT.md)")

    if cards:
        lines.extend(
            [
                "",
                f"## {fit_heading}",
                "",
                fit_blurb,
                "",
            ]
        )
        lines.extend(
            _md_table(
                [
                    "PDK",
                    "Model",
                    "Weighted err",
                    "RMSE lin (A)",
                    "RMSE log (dec)",
                    "Fit wall (s)",
                    "Evals",
                    "Peak RSS (KB)",
                ],
                [
                    [
                        c["pdk"],
                        c["model"],
                        _fmt(float(c["weighted_error"])),
                        _fmt(float(c["rmse_linear"])),
                        _fmt(float(c["rmse_log"])),
                        f"{float(c['fit_wall_s']):.2f}",
                        c["n_evals"],
                        c["peak_rss_kb"],
                    ]
                    for c in sorted(cards, key=lambda x: (x["pdk"], x["model"]))
                ],
            )
        )
        for model in models:
            model_cards = [c for c in cards if c["model"] == model]
            for card in sorted(model_cards, key=lambda x: str(x["pdk"])):
                pdk = str(card["pdk"])
                plot = results_dir / model / "fit" / f"{pdk}_idvg_fit.png"
                if plot.is_file():
                    rel = f"{model}/fit/{pdk}_idvg_fit.png"
                    lines.extend(
                        [
                            "",
                            f"### {model} / {pdk} — Id–Vg fit",
                            "",
                            f"![Id-Vg fit]({rel})",
                            "",
                        ]
                    )
            combined = results_dir / model / "fit" / "error_vs_iteration.png"
            if combined.is_file():
                lines.extend(
                    [
                        "",
                        f"### {model} — fit convergence",
                        "",
                        f"![error vs iteration]({model}/fit/error_vs_iteration.png)",
                        "",
                    ]
                )

    if predict_rows:
        bench_blurb = (
            "ACM-only waveforms from the **fitted card** (no BSIM reference). "
            "Shown for portability smoke and custom user-input reporting."
            if capabilities.get("user_supplied_only")
            else "Cross-simulator portability of the **fitted ACM card** "
            "(no BSIM reference in these netlists)."
        )
        lines.extend(
            [
                "",
                "## Predict benches (ACM-only)",
                "",
                bench_blurb,
                "",
            ]
        )
        lines.extend(
            _md_table(
                ["PDK", "Model", "Sim", "Analysis", "Status", "Runtime (s)", "Peak RSS (KB)"],
                [
                    [
                        r["pdk"],
                        r["model"],
                        r["simulator"],
                        r["analysis"],
                        "ok" if _status_ok(r) else "FAIL",
                        r["runtime_s"],
                        r["peak_rss_kb"],
                    ]
                    for r in sorted(
                        predict_rows,
                        key=lambda x: (
                            x["pdk"],
                            x["model"],
                            x["simulator"],
                            x["analysis"],
                        ),
                    )
                ],
            )
        )
        for model in models:
            plot_root = results_dir / model / "plots"
            if not plot_root.is_dir():
                continue
            for plot in sorted(plot_root.rglob("bench_*.png")):
                rel = plot.relative_to(results_dir).as_posix()
                label = plot.stem.replace("bench_", "").upper()
                pdk = plot.parent.name
                lines.extend(
                    [
                        "",
                        f"### {model} / {pdk} — {label} (ACM predict)",
                        "",
                        f"![{label} predict]({rel})",
                        "",
                    ]
                )

    if eval_rows:
        lines.extend(
            [
                "",
                "## Eval suite (ACM vs reference golden)",
                "",
                eval_blurb,
                "",
            ]
        )
        lines.extend(
            _md_table(
                [
                    "PDK",
                    "Model",
                    "Sim",
                    "Analysis",
                    "Status",
                    "Metric",
                    "Primary",
                    "RMSE log",
                    "Runtime (s)",
                    "Peak RSS (KB)",
                ],
                _eval_table_rows(eval_rows, include_model=True),
            )
        )
        for model in models:
            plot_root = results_dir / model / "plots"
            if not plot_root.is_dir():
                continue
            for plot in sorted(plot_root.rglob("eval_*.png")):
                rel = plot.relative_to(results_dir).as_posix()
                label = plot.stem.replace("eval_", "").upper()
                pdk = plot.parent.name
                lines.extend(
                    [
                        "",
                        f"### {model} / {pdk} — {label}",
                        "",
                        f"![{label}]({rel})",
                        "",
                    ]
                )

    lines.append("")
    return lines


def _build_model_report(
    *,
    model: str,
    cards: Sequence[Mapping[str, Any]],
    predict_rows: Sequence[Mapping[str, Any]],
    eval_rows: Sequence[Mapping[str, Any]],
    fit_dir: Path,
    report_dir: Path,
    stamp: str,
    sources: Sequence[Mapping[str, Any]],
    capabilities: Mapping[str, bool],
) -> list[str]:
    """Compose one model REPORT.md body."""
    ref_name = "user Id–Vg CSV" if capabilities.get("user_supplied_only") else "PDK BSIM golden"
    lines: list[str] = [
        f"# {model} REPORT",
        "",
        f"_Generated {stamp}_",
        "",
        "[← SUMMARY](../SUMMARY.md)",
        "",
        "## Metrics guide",
        "",
        f"- **Fit**: ACM DC params vs {ref_name} Id–Vg.",
        "- **Predict**: ACM-only portability smoke across simulators.",
        "- **Eval**: Golden reference waveforms vs ACM (when BSIM refs are available).",
        "",
    ]

    if sources:
        lines.extend(
            [
                "## Input sources",
                "",
            ]
        )
        lines.extend(
            _md_table(
                ["Target", "Source", "VDD (V)", "W (m)", "L (m)", "Polarity", "Corner"],
                [
                    [
                        row["target"],
                        _source_label(str(row["source"])),
                        _fmt_geom(row["vdd"]),
                        _fmt_geom(row["width_m"]),
                        _fmt_geom(row["length_m"]),
                        row["polarity"],
                        row["corner"],
                    ]
                    for row in sources
                ],
            )
        )
        lines.append("")

    if cards:
        fit_title = (
            "Fitted parameters (user Id–Vg reference)"
            if capabilities.get("user_supplied_only")
            else "Fitted parameters (golden I-V vs BSIM)"
        )
        lines.extend([f"## {fit_title}", ""])
        lines.extend(
            _md_table(
                [
                    "PDK",
                    "Weighted err",
                    "RMSE lin (A)",
                    "RMSE log (dec)",
                    "Fit wall (s)",
                    "Evals",
                    "Peak RSS (KB)",
                ],
                [
                    [
                        c["pdk"],
                        _fmt(float(c["weighted_error"])),
                        _fmt(float(c["rmse_linear"])),
                        _fmt(float(c["rmse_log"])),
                        f"{float(c['fit_wall_s']):.2f}",
                        c["n_evals"],
                        c["peak_rss_kb"],
                    ]
                    for c in sorted(cards, key=lambda x: str(x["pdk"]))
                ],
            )
        )
        lines.append("")
        for card in sorted(cards, key=lambda c: str(c["pdk"])):
            pdk = card["pdk"]
            params = card["parameters"]
            param_bits = ", ".join(
                f"{k}={params[k]:.6g}"
                if isinstance(params[k], float)
                else f"{k}={params[k]}"
                for k in sorted(params)
            )
            lines.extend(
                [
                    f"### {pdk}",
                    "",
                    f"- Card: `fit/{pdk}.json`",
                    f"- Parameters: `{param_bits}`",
                    "",
                ]
            )
            plot = fit_dir / f"{pdk}_error_vs_iter.png"
            if not plot.is_file():
                raise FileNotFoundError(plot)
            rel = Path(os.path.relpath(plot, start=report_dir)).as_posix()
            lines.extend([f"![error vs iteration]({rel})", ""])
            idvg_plot = fit_dir / f"{pdk}_idvg_fit.png"
            if idvg_plot.is_file():
                rel_idvg = Path(os.path.relpath(idvg_plot, start=report_dir)).as_posix()
                lines.extend(
                    [
                        f"![Id-Vg fit overlay]({rel_idvg})",
                        "",
                    ]
                )
        combined = fit_dir / "error_vs_iteration.png"
        if combined.is_file():
            rel = Path(os.path.relpath(combined, start=report_dir)).as_posix()
            lines.extend(["### Fit convergence (all PDKs)", "", f"![]({rel})", ""])

    predict_heading = (
        "## Predict benches (ACM-only)"
        if capabilities.get("user_supplied_only")
        else "## Predict benches (ACM-only, all simulators)"
    )
    predict_blurb = (
        "Waveforms simulated from the fitted ACM card (no reference device). "
        "Use these for AC/noise/temp/transient reporting when only Id–Vg input was supplied."
        if capabilities.get("user_supplied_only")
        else "Portability smoke of the fitted card (no BSIM reference device)."
    )
    lines.extend(
        [
            predict_heading,
            "",
            predict_blurb,
            "",
        ]
    )
    if not predict_rows:
        lines.append("_No predict benches found._")
        lines.append("")
    else:
        sims = sorted({str(r["simulator"]) for r in predict_rows})
        lines.append(f"Simulators: {', '.join(f'`{s}`' for s in sims)}")
        lines.append("")
        lines.extend(
            _md_table(
                ["PDK", "Sim", "Analysis", "Status", "Runtime (s)", "Peak RSS (KB)"],
                [
                    [
                        r["pdk"],
                        r["simulator"],
                        r["analysis"],
                        "ok" if _status_ok(r) else "FAIL",
                        r["runtime_s"],
                        r["peak_rss_kb"],
                    ]
                    for r in sorted(
                        predict_rows,
                        key=lambda x: (x["pdk"], x["simulator"], x["analysis"]),
                    )
                ],
            )
        )
        lines.append("")
        plot_root = report_dir / "plots"
        if plot_root.is_dir():
            bench_plots = sorted(plot_root.rglob("bench_*.png"))
            if bench_plots:
                lines.extend(["### ACM waveform plots", ""])
                for plot in bench_plots:
                    rel = Path(os.path.relpath(plot, start=report_dir)).as_posix()
                    label = plot.stem.replace("bench_", "").upper()
                    pdk = plot.parent.name
                    lines.extend(
                        [
                            f"#### {pdk} — {label}",
                            "",
                            f"![{label}]({rel})",
                            "",
                        ]
                    )

    lines.extend(
        [
            "## Eval suite (ACM vs ngspice PDK golden)",
            "",
            "Accuracy = RMSE(ACM, golden ngspice PDK BSIM). "
            "Runtime / peak RSS are **ACM-only**.",
            "",
        ]
    )
    if not eval_rows:
        lines.append("_No eval-suite rows for this model (fit-only or user CSV input)._")
        lines.append("")
    else:
        lines.extend(
            _md_table(
                [
                    "PDK",
                    "Sim",
                    "Analysis",
                    "Status",
                    "Metric",
                    "Primary",
                    "RMSE log",
                    "Runtime (s)",
                    "Peak RSS (KB)",
                ],
                _eval_table_rows(eval_rows, include_model=False),
            )
        )
        lines.append("")
        plot_root = report_dir / "plots"
        if plot_root.is_dir():
            lines.extend(["## Eval waveform overlays", ""])
            for plot in sorted(plot_root.rglob("eval_*.png")):
                rel = Path(os.path.relpath(plot, start=report_dir)).as_posix()
                label = plot.stem.replace("eval_", "").upper()
                pdk = plot.parent.name
                lines.extend(
                    [
                        f"### {pdk} — {label}",
                        "",
                        f"![{label}]({rel})",
                        "",
                    ]
                )

    return lines


__all__ = ["write_regression_reports"]
