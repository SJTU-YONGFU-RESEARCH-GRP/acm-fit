"""Parallel ACM-vs-golden evaluation suite (ngspice PDK BSIM reference)."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from acm_opt.models import ModelSpec, resolve_models

from .cache import (
    JobFingerprint,
    file_sha256,
    fingerprint_digest,
    should_skip,
    write_cache,
)
from .config import (
    SUPPORTED_ANALYSES,
    SUPPORTED_SIMULATORS,
    SuiteConfig,
    load_suite_config,
)
from .export import (
    assert_hspice_va_loaded,
    export_hspice_waveform,
    export_ngspice_waveform,
    export_spectre_waveform,
)
from .metrics import compare_to_golden
from .netlists import (
    format_instance_params,
    write_acm_hspice,
    write_acm_ngspice,
    write_acm_spectre,
    write_bsim_ref_ngspice,
)
from .simulators import require_simulator, run_simulator
from .waveforms import ensure_hspice_va_path


@dataclass(frozen=True)
class EvalJob:
    """One (pdk, model, simulator, analysis) ACM evaluation job."""

    pdk: str
    model: str
    simulator: str
    analysis: str
    job_dir: Path


@dataclass(frozen=True)
class EvalJobResult:
    """Outcome of one evaluation job."""

    pdk: str
    model: str
    simulator: str
    analysis: str
    status: str
    runtime_s: float
    peak_rss_kb: int
    metrics: Mapping[str, Any]
    message: str


def _eval_model_specs(
    repo_root: Path,
    model_names: Sequence[str],
) -> dict[str, ModelSpec]:
    """Resolve eval models from the ACM registry."""
    out: dict[str, ModelSpec] = {}
    for name in model_names:
        resolved = resolve_models(repo_root, (name,))
        out[name] = resolved[0]
    return out


def _compile_osdi(model: ModelSpec, openvaf: Path) -> None:
    """Compile Verilog-A to OSDI when needed for ngspice."""
    if model.osdi_path.is_file():
        if model.osdi_path.stat().st_mtime >= model.va_path.stat().st_mtime:
            return
    if not openvaf.is_file():
        raise FileNotFoundError(f"OpenVAF binary missing: {openvaf}")
    proc = subprocess.run(
        [str(openvaf), str(model.va_path)],
        cwd=str(model.va_path.parent),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not model.osdi_path.is_file():
        raise RuntimeError(
            f"OpenVAF failed for {model.va_path}:\n{proc.stdout}\n{proc.stderr}"
        )


def _ensure_spiceinit(job_dir: Path) -> None:
    """Write ngspice PDK-compatible init file."""
    spiceinit = job_dir / ".spiceinit"
    if not spiceinit.exists():
        spiceinit.write_text("set ngbehavior=hs\n")


def _load_fitted_card(results_dir: Path, model: str, pdk: str) -> dict[str, Any]:
    """Load ``results/<model>/fit/<pdk>.json`` fitted card."""
    path = results_dir / model / "fit" / f"{pdk}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"missing fitted card {path}; run golden fit before eval"
        )
    payload = json.loads(path.read_text())
    if payload.get("model") != model or payload.get("pdk") != pdk:
        raise ValueError(f"{path}: model/pdk mismatch with request {model}/{pdk}")
    if "parameters" not in payload or "vdd" not in payload:
        raise ValueError(f"{path}: missing parameters/vdd")
    return payload


def _capture_one_golden_ref(
    *,
    suite: SuiteConfig,
    results_dir: Path,
    pdk: str,
    analysis: str,
    force: bool,
) -> tuple[tuple[str, str], Path]:
    """Capture one ngspice PDK-BSIM reference waveform."""
    pdk_cfg = suite.pdks[pdk]
    ref_dir = results_dir / "golden" / pdk / "ref" / analysis
    ref_csv = ref_dir / "ref.csv"
    marker = ref_dir / "SUCCESS"
    fp_path = ref_dir / "fingerprint.json"
    digest_payload = {
        "suite_version": suite.suite_version,
        "pdk": pdk,
        "analysis": analysis,
        "analysis_params": suite.analysis_defaults[analysis],
        "pdk_section": pdk_cfg.sections["ngspice"],
        "ref_device": pdk_cfg.ref_devices["ngspice"],
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if (
        not force
        and marker.is_file()
        and ref_csv.is_file()
        and fp_path.is_file()
        and json.loads(fp_path.read_text()).get("digest") == digest
    ):
        return (pdk, analysis), ref_csv

    ref_dir.mkdir(parents=True, exist_ok=True)
    _ensure_spiceinit(ref_dir)
    raw = ref_dir / "ref_out.txt"
    net = ref_dir / "ref.spice"
    write_bsim_ref_ngspice(
        path=net,
        title=f"golden BSIM {pdk} {analysis}",
        pdk=pdk_cfg,
        analysis=analysis,
        analysis_params=suite.analysis_defaults[analysis],
        out_txt=raw.resolve(),
    )
    sim = run_simulator(
        simulator="ngspice",
        netlist=net,
        cwd=ref_dir,
        log_path=ref_dir / "run.log",
    )
    if sim.returncode != 0:
        raise RuntimeError(
            f"golden BSIM capture failed for {pdk}/{analysis}; "
            f"see {ref_dir / 'run.log'}"
        )
    export_ngspice_waveform(
        analysis=analysis,
        raw_path=raw,
        csv_path=ref_csv,
    )
    fp_path.write_text(
        json.dumps({"digest": digest, **digest_payload}, indent=2) + "\n"
    )
    marker.write_text("ok\n")
    (ref_dir / "metrics_meta.json").write_text(
        json.dumps(
            {
                "runtime_s": sim.runtime_s,
                "peak_rss_kb": sim.peak_rss_kb,
            },
            indent=2,
        )
        + "\n"
    )
    return (pdk, analysis), ref_csv


def capture_golden_refs(
    *,
    suite: SuiteConfig,
    results_dir: Path,
    pdks: Sequence[str],
    analyses: Sequence[str],
    force: bool = False,
    jobs: int = 1,
) -> dict[tuple[str, str], Path]:
    """Capture ngspice PDK-BSIM reference waveforms under ``golden/<pdk>/ref/``."""
    if jobs < 1:
        raise ValueError(f"jobs must be >= 1, got {jobs}")
    tasks = [(pdk, analysis) for pdk in pdks for analysis in analyses]
    if not tasks:
        return {}

    out: dict[tuple[str, str], Path] = {}
    with ThreadPoolExecutor(max_workers=min(jobs, len(tasks))) as pool:
        futures = {
            pool.submit(
                _capture_one_golden_ref,
                suite=suite,
                results_dir=results_dir,
                pdk=pdk,
                analysis=analysis,
                force=force,
            ): (pdk, analysis)
            for pdk, analysis in tasks
        }
        for fut in as_completed(futures):
            key, ref_csv = fut.result()
            out[key] = ref_csv
    return out


def _run_one_job(
    *,
    job: EvalJob,
    suite: SuiteConfig,
    model: ModelSpec,
    card: Mapping[str, float],
    vdd: float,
    analysis_params: Mapping[str, Any],
    ref_csv: Path,
    repo_root: Path,
    force: bool,
) -> EvalJobResult:
    """Execute or skip one ACM-only evaluation job vs golden ref."""
    pdk_cfg = suite.pdks[job.pdk]
    va_hash = file_sha256(model.va_path)
    osdi_hash = (
        file_sha256(model.osdi_path)
        if job.simulator == "ngspice" and model.osdi_path.is_file()
        else "none"
    )
    fp = JobFingerprint(
        suite_version=suite.suite_version,
        pdk=job.pdk,
        model=job.model,
        simulator=job.simulator,
        analysis=job.analysis,
        va_sha256=va_hash,
        osdi_sha256=osdi_hash,
        card={k: float(v) for k, v in card.items()},
        analysis_params=dict(analysis_params),
        pdk_section=pdk_cfg.sections["ngspice"],
        ref_device=pdk_cfg.ref_devices["ngspice"],
    )
    digest = fingerprint_digest(fp)
    metrics_path = job.job_dir / "metrics.json"
    if not force and should_skip(job.job_dir, digest) and metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text())
        return EvalJobResult(
            pdk=job.pdk,
            model=job.model,
            simulator=job.simulator,
            analysis=job.analysis,
            status="skipped",
            runtime_s=float(metrics.get("runtime_s", 0.0)),
            peak_rss_kb=int(metrics.get("peak_rss_kb", 0)),
            metrics=metrics.get("analysis", {}),
            message="unchanged model/fingerprint",
        )

    job.job_dir.mkdir(parents=True, exist_ok=True)
    _ensure_spiceinit(job.job_dir)
    params = format_instance_params(model, card, pdk_cfg)
    title = f"{job.model} {job.analysis} vs golden {job.pdk} ({job.simulator})"
    acm_csv = job.job_dir / "acm.csv"
    log_path = job.job_dir / "run.log"
    hspice_hdl: Path | None = None

    if job.simulator == "ngspice":
        netlist = job.job_dir / f"{job.analysis}.spice"
        raw = job.job_dir / f"{job.analysis}_out.txt"
        write_acm_ngspice(
            path=netlist,
            title=title,
            model=model,
            params=params,
            osdi=model.osdi_path.resolve(),
            analysis=job.analysis,
            analysis_params=analysis_params,
            vdd=vdd,
            out_txt=raw.resolve(),
        )
    elif job.simulator == "spectre":
        netlist = job.job_dir / f"{job.analysis}.scs"
        write_acm_spectre(
            path=netlist,
            title=title,
            model=model,
            params=params,
            va_path=model.va_path.resolve(),
            analysis=job.analysis,
            analysis_params=analysis_params,
            vdd=vdd,
        )
    elif job.simulator == "hspice":
        netlist = job.job_dir / f"{job.analysis}.sp"
        write_acm_hspice(
            path=netlist,
            title=title,
            model=model,
            params=params,
            analysis=job.analysis,
            analysis_params=analysis_params,
            vdd=vdd,
        )
        hspice_hdl = ensure_hspice_va_path(
            model.va_path,
            repo_root / "work" / "hspice_va",
        )
    else:
        raise ValueError(f"unsupported simulator: {job.simulator!r}")

    sim = run_simulator(
        simulator=job.simulator,
        netlist=netlist,
        cwd=job.job_dir,
        log_path=log_path,
        hspice_hdl=hspice_hdl,
    )
    if sim.returncode != 0:
        return EvalJobResult(
            pdk=job.pdk,
            model=job.model,
            simulator=job.simulator,
            analysis=job.analysis,
            status="failed",
            runtime_s=sim.runtime_s,
            peak_rss_kb=sim.peak_rss_kb,
            metrics={},
            message=f"simulator exit {sim.returncode}; see {log_path}",
        )

    try:
        if job.simulator == "ngspice":
            export_ngspice_waveform(
                analysis=job.analysis,
                raw_path=job.job_dir / f"{job.analysis}_out.txt",
                csv_path=acm_csv,
            )
        elif job.simulator == "spectre":
            # Spectre success check
            slog = job.job_dir / "spectre_run.log"
            stext = slog.read_text(errors="ignore") if slog.is_file() else ""
            if "Error found by spectre" in stext or "terminated prematurely" in stext:
                if "completes with 0 errors" not in stext:
                    raise RuntimeError(f"spectre reported errors; see {slog}")
            export_spectre_waveform(
                analysis=job.analysis,
                job_dir=job.job_dir,
                netlist_stem=job.analysis,
                csv_path=acm_csv,
            )
        else:
            lis = job.job_dir / f"{job.analysis}.lis"
            assert_hspice_va_loaded(lis)
            export_hspice_waveform(
                analysis=job.analysis,
                lis_path=lis,
                csv_path=acm_csv,
            )
        analysis_metrics = compare_to_golden(job.analysis, ref_csv, acm_csv)
    except (ValueError, FileNotFoundError, OSError, RuntimeError) as exc:
        return EvalJobResult(
            pdk=job.pdk,
            model=job.model,
            simulator=job.simulator,
            analysis=job.analysis,
            status="failed",
            runtime_s=sim.runtime_s,
            peak_rss_kb=sim.peak_rss_kb,
            metrics={},
            message=f"metrics/export error: {exc}",
        )

    payload = {
        "runtime_s": sim.runtime_s,
        "peak_rss_kb": sim.peak_rss_kb,
        "analysis": analysis_metrics,
        "ref_csv": str(ref_csv),
        "acm_csv": str(acm_csv),
    }
    metrics_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    write_cache(job.job_dir, digest, fp)
    return EvalJobResult(
        pdk=job.pdk,
        model=job.model,
        simulator=job.simulator,
        analysis=job.analysis,
        status="ok",
        runtime_s=sim.runtime_s,
        peak_rss_kb=sim.peak_rss_kb,
        metrics=analysis_metrics,
        message="completed",
    )


def _write_eval_csv(path: Path, results: list[EvalJobResult]) -> None:
    """Write eval summary CSV."""
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "pdk",
                "model",
                "simulator",
                "analysis",
                "status",
                "runtime_s",
                "peak_rss_kb",
                "message",
                "metrics_json",
            ]
        )
        for row in results:
            writer.writerow(
                [
                    row.pdk,
                    row.model,
                    row.simulator,
                    row.analysis,
                    row.status,
                    row.runtime_s,
                    row.peak_rss_kb,
                    row.message,
                    json.dumps(row.metrics, sort_keys=True),
                ]
            )


def run_eval_suite(
    *,
    repo_root: Path,
    config_path: Path,
    results_dir: Path,
    openvaf_binary: Path,
    models: Sequence[str],
    pdks: Sequence[str],
    analyses: Sequence[str] | None = None,
    simulators: Sequence[str] | None = None,
    jobs: int = 4,
    force: bool = False,
) -> dict[str, Path]:
    """Run golden-BSIM capture then ACM-only cross-sim evaluation."""
    suite = load_suite_config(config_path, repo_root)
    selected_analyses = tuple(analyses or suite.default_analyses)
    selected_sims = tuple(simulators or suite.default_simulators)

    unknown_a = [a for a in selected_analyses if a not in SUPPORTED_ANALYSES]
    unknown_s = [s for s in selected_sims if s not in SUPPORTED_SIMULATORS]
    if unknown_a:
        raise ValueError(f"unsupported analyses: {unknown_a}")
    if unknown_s:
        raise ValueError(f"unsupported simulators: {unknown_s}")
    if jobs < 1:
        raise ValueError(f"jobs must be >= 1, got {jobs}")

    for sim in selected_sims:
        require_simulator(sim)
    require_simulator("ngspice")

    for pdk in pdks:
        if pdk not in suite.pdks:
            raise ValueError(f"unknown PDK {pdk!r}; known={sorted(suite.pdks)}")
        section = suite.pdks[pdk].sections["ngspice"]
        if '""' in section or not section.strip():
            raise ValueError(f"PDK '{pdk}' ngspice library path is unset")

    model_map = _eval_model_specs(repo_root, models)
    if "ngspice" in selected_sims:
        compiled: set[Path] = set()
        for model in model_map.values():
            if model.va_path in compiled:
                continue
            _compile_osdi(model, openvaf_binary)
            compiled.add(model.va_path)

    results_dir = results_dir.resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    golden_refs = capture_golden_refs(
        suite=suite,
        results_dir=results_dir,
        pdks=pdks,
        analyses=selected_analyses,
        force=force,
        jobs=jobs,
    )

    planned: list[
        tuple[EvalJob, ModelSpec, Mapping[str, float], float, Mapping[str, Any], Path]
    ] = []
    for pdk in pdks:
        for model_name, model in model_map.items():
            fitted = _load_fitted_card(results_dir, model_name, pdk)
            card = {k: float(v) for k, v in fitted["parameters"].items()}
            vdd = float(fitted["vdd"])
            for sim in selected_sims:
                for analysis in selected_analyses:
                    job_dir = results_dir / model_name / "eval" / pdk / sim / analysis
                    planned.append(
                        (
                            EvalJob(
                                pdk=pdk,
                                model=model_name,
                                simulator=sim,
                                analysis=analysis,
                                job_dir=job_dir,
                            ),
                            model,
                            card,
                            vdd,
                            suite.analysis_defaults[analysis],
                            golden_refs[(pdk, analysis)],
                        )
                    )

    results: list[EvalJobResult] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(
                _run_one_job,
                job=job,
                suite=suite,
                model=model,
                card=card,
                vdd=vdd,
                analysis_params=aparams,
                ref_csv=ref_csv,
                repo_root=repo_root,
                force=force,
            ): job
            for job, model, card, vdd, aparams, ref_csv in planned
        }
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: (r.pdk, r.model, r.simulator, r.analysis))
    failed = [r for r in results if r.status == "failed"]

    by_model: dict[str, list[EvalJobResult]] = {}
    for row in results:
        by_model.setdefault(row.model, []).append(row)
    written: dict[str, Path] = {}
    for model_name, rows in by_model.items():
        eval_dir = results_dir / model_name / "eval"
        eval_dir.mkdir(parents=True, exist_ok=True)
        _write_eval_csv(eval_dir / "summary.csv", rows)
        summary = {
            "n_jobs": len(rows),
            "n_ok": sum(1 for r in rows if r.status == "ok"),
            "n_skipped": sum(1 for r in rows if r.status == "skipped"),
            "n_failed": sum(1 for r in rows if r.status == "failed"),
            "reference": "ngspice_pdk_bsim_golden",
            "results": [
                {
                    "pdk": r.pdk,
                    "model": r.model,
                    "simulator": r.simulator,
                    "analysis": r.analysis,
                    "status": r.status,
                    "runtime_s": r.runtime_s,
                    "peak_rss_kb": r.peak_rss_kb,
                    "message": r.message,
                    "metrics": dict(r.metrics),
                }
                for r in rows
            ],
        }
        json_path = eval_dir / "summary.json"
        json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        written[model_name] = json_path

    if failed:
        details = "; ".join(
            f"{r.pdk}/{r.model}/{r.simulator}/{r.analysis}: {r.message}"
            for r in failed
        )
        raise RuntimeError(f"{len(failed)} eval job(s) failed: {details}")
    return written


__all__ = ["run_eval_suite", "EvalJobResult", "capture_golden_refs"]
