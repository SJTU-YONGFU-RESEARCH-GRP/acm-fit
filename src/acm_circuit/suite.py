"""Run Adornes circuit benchmark suite."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from acm_circuit.cards import load_device_card
from acm_circuit.config import CircuitSuiteConfig, load_circuit_suite
from acm_circuit.metrics import (
    ac_gain_db_rmse,
    estimate_osc_freq_hz,
    parse_ngspice_print,
    vtc_rmse,
)
from acm_circuit.netlists import (
    write_cs_amp_acm,
    write_cs_amp_bsim,
    write_inverter_vtc_acm,
    write_inverter_vtc_bsim,
    write_ring_osc_acm,
    write_ring_osc_bsim,
    write_sbcs_acm,
    write_sbcs_bsim,
)
from acm_eval.simulators import run_simulator
from acm_opt.models import ModelSpec, resolve_models, resolve_polarity_model


@dataclass(frozen=True)
class CircuitRunResult:
    """One circuit / model / PDK result row."""

    circuit: str
    pdk: str
    model: str
    analysis: str
    metrics: Mapping[str, Any]
    job_dir: Path


def _run_ngspice(netlist: Path, cwd: Path) -> None:
    result = run_simulator(
        simulator="ngspice",
        netlist=netlist,
        cwd=cwd,
        log_path=cwd / f"{netlist.stem}.log",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ngspice failed: {netlist} (see {result.log_path})")


def _osc_freq_hz(wave_csv: Path) -> float:
    """Return oscillation frequency, or NaN when the waveform does not oscillate."""
    try:
        return estimate_osc_freq_hz(wave_csv)
    except ValueError:
        return float("nan")


def _device_geom(cfg: CircuitSuiteConfig, role: str) -> tuple[float, float]:
    inv = cfg.device_roles[role]
    return float(inv["nmos"]["width_m"]), float(inv["nmos"]["length_m"])


def _load_mos_cards(
    *,
    results_dir: Path,
    repo_root: Path,
    model_name: str,
    pdk: str,
    width_m: float,
    length_m: float,
) -> tuple[ModelSpec, ModelSpec, Mapping[str, float], Mapping[str, float]]:
    nmos = load_device_card(
        results_dir=results_dir,
        model=resolve_models(repo_root, (model_name,))[0],
        repo_root=repo_root,
        model_name=model_name,
        pdk=pdk,
        polarity="nmos",
        width_m=width_m,
        length_m=length_m,
    )
    pmos = load_device_card(
        results_dir=results_dir,
        model=resolve_models(repo_root, (model_name,))[0],
        repo_root=repo_root,
        model_name=model_name,
        pdk=pdk,
        polarity="pmos",
        width_m=width_m,
        length_m=length_m,
    )
    return (
        nmos["model_spec"],
        pmos["model_spec"],
        nmos["parameters"],
        pmos["parameters"],
    )


def _run_inverter(
    *,
    cfg: CircuitSuiteConfig,
    repo_root: Path,
    results_dir: Path,
    pdk_name: str,
    model_name: str,
    job_root: Path,
) -> list[CircuitRunResult]:
    pdk = cfg.pdk_targets[pdk_name]
    w_m, l_m = _device_geom(cfg, "inverter")
    vdds = [float(v) for v in cfg.circuits["inverter"]["vdd_sweep_v"]]
    out_rows: list[CircuitRunResult] = []
    ref_root = job_root / "golden" / pdk_name / "inverter"
    for vdd in vdds:
        tag = f"vdd_{vdd:.3g}".replace(".", "p")
        ref_dir = ref_root / tag
        ref_dir.mkdir(parents=True, exist_ok=True)
        ref_sp = ref_dir / "vtc.spice"
        ref_csv = ref_dir / "vtc.txt"
        write_inverter_vtc_bsim(
            path=ref_sp,
            pdk=pdk,
            width_m=w_m,
            length_m=l_m,
            vdd=vdd,
            v_step=max(vdd / 100.0, 0.01),
            out_csv=ref_csv,
        )
        _run_ngspice(ref_sp, ref_dir)

        nmos_m, pmos_m, n_card, p_card = _load_mos_cards(
            results_dir=results_dir,
            repo_root=repo_root,
            model_name=model_name,
            pdk=pdk_name,
            width_m=w_m,
            length_m=l_m,
        )
        acm_dir = job_root / model_name / pdk_name / "inverter" / tag
        acm_dir.mkdir(parents=True, exist_ok=True)
        acm_sp = acm_dir / "vtc.spice"
        acm_csv = acm_dir / "vtc.txt"
        write_inverter_vtc_acm(
            path=acm_sp,
            pdk=pdk,
            nmos_model=nmos_m,
            pmos_model=pmos_m,
            nmos_card=n_card,
            pmos_card=p_card,
            width_m=w_m,
            length_m=l_m,
            vdd=vdd,
            v_step=max(vdd / 100.0, 0.01),
            out_csv=acm_csv,
        )
        _run_ngspice(acm_sp, acm_dir)
        metrics = vtc_rmse(ref_csv, acm_csv)
        metrics["vdd_v"] = vdd
        out_rows.append(
            CircuitRunResult(
                circuit="inverter",
                pdk=pdk_name,
                model=model_name,
                analysis="dc_vtc",
                metrics=metrics,
                job_dir=acm_dir,
            )
        )
    return out_rows


def _run_ring_osc(
    *,
    cfg: CircuitSuiteConfig,
    repo_root: Path,
    results_dir: Path,
    pdk_name: str,
    model_name: str,
    job_root: Path,
) -> list[CircuitRunResult]:
    pdk = cfg.pdk_targets[pdk_name]
    w_m, l_m = _device_geom(cfg, "ring_osc")
    stages = int(cfg.device_roles["ring_osc"]["stages"])
    vdds = [float(v) for v in cfg.circuits["ring_osc"]["vdd_sweep_v"]]
    out_rows: list[CircuitRunResult] = []
    ref_root = job_root / "golden" / pdk_name / "ring_osc"
    for vdd in vdds:
        tag = f"vdd_{vdd:.3g}".replace(".", "p")
        t_stop = max(20.0 / vdd, 5e-7)
        ref_dir = ref_root / tag
        ref_dir.mkdir(parents=True, exist_ok=True)
        ref_sp = ref_dir / "tran.spice"
        ref_csv = ref_dir / "wave.txt"
        write_ring_osc_bsim(
            path=ref_sp,
            pdk=pdk,
            width_m=w_m,
            length_m=l_m,
            stages=stages,
            vdd=vdd,
            t_stop_s=t_stop,
            out_csv=ref_csv,
        )
        _run_ngspice(ref_sp, ref_dir)
        f_bsim = _osc_freq_hz(ref_csv)

        nmos_m, pmos_m, n_card, p_card = _load_mos_cards(
            results_dir=results_dir,
            repo_root=repo_root,
            model_name=model_name,
            pdk=pdk_name,
            width_m=w_m,
            length_m=l_m,
        )
        acm_dir = job_root / model_name / pdk_name / "ring_osc" / tag
        acm_dir.mkdir(parents=True, exist_ok=True)
        acm_sp = acm_dir / "tran.spice"
        acm_csv = acm_dir / "wave.txt"
        write_ring_osc_acm(
            path=acm_sp,
            pdk=pdk,
            nmos_model=nmos_m,
            pmos_model=pmos_m,
            nmos_card=n_card,
            pmos_card=p_card,
            width_m=w_m,
            length_m=l_m,
            stages=stages,
            vdd=vdd,
            t_stop_s=t_stop,
            out_csv=acm_csv,
        )
        _run_ngspice(acm_sp, acm_dir)
        f_acm = _osc_freq_hz(acm_csv)
        ratio = f_acm / f_bsim if f_bsim > 0 else float("nan")
        out_rows.append(
            CircuitRunResult(
                circuit="ring_osc",
                pdk=pdk_name,
                model=model_name,
                analysis="tran",
                metrics={
                    "vdd_v": vdd,
                    "f_osc_hz_bsim": f_bsim,
                    "f_osc_hz_acm": f_acm,
                    "f_osc_ratio": ratio,
                },
                job_dir=acm_dir,
            )
        )
    return out_rows


def _run_sbcs(
    *,
    cfg: CircuitSuiteConfig,
    repo_root: Path,
    results_dir: Path,
    pdk_name: str,
    model_name: str,
    job_root: Path,
) -> list[CircuitRunResult]:
    pdk = cfg.pdk_targets[pdk_name]
    w_m, l_m = _device_geom(cfg, "inverter")
    vdd = pdk.vdd * 0.25
    ref_dir = job_root / "golden" / pdk_name / "sbcs"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_sp = ref_dir / "op.spice"
    ref_meas = ref_dir / "meas.txt"
    write_sbcs_bsim(path=ref_sp, pdk=pdk, vdd=vdd, out_meas=ref_meas)
    _run_ngspice(ref_sp, ref_dir)
    ref_vals = parse_ngspice_print(ref_meas)

    nmos_m, pmos_m, n_card, p_card = _load_mos_cards(
        results_dir=results_dir,
        repo_root=repo_root,
        model_name=model_name,
        pdk=pdk_name,
        width_m=w_m,
        length_m=l_m,
    )
    acm_dir = job_root / model_name / pdk_name / "sbcs"
    acm_dir.mkdir(parents=True, exist_ok=True)
    acm_sp = acm_dir / "op.spice"
    acm_meas = acm_dir / "meas.txt"
    write_sbcs_acm(
        path=acm_sp,
        pdk=pdk,
        nmos_model=nmos_m,
        pmos_model=pmos_m,
        nmos_card=n_card,
        pmos_card=p_card,
        vdd=vdd,
        out_meas=acm_meas,
    )
    _run_ngspice(acm_sp, acm_dir)
    acm_vals = parse_ngspice_print(acm_meas)
    metrics: dict[str, Any] = {"vdd_v": vdd}
    for key in set(ref_vals) | set(acm_vals):
        if key in ref_vals and key in acm_vals:
            metrics[f"{key}_bsim"] = ref_vals[key]
            metrics[f"{key}_acm"] = acm_vals[key]
            metrics[f"{key}_rel_err"] = abs(acm_vals[key] - ref_vals[key]) / (
                abs(ref_vals[key]) + 1e-18
            )
    return [
        CircuitRunResult(
            circuit="sbcs",
            pdk=pdk_name,
            model=model_name,
            analysis="dc_op",
            metrics=metrics,
            job_dir=acm_dir,
        )
    ]


def _run_cs_amp(
    *,
    cfg: CircuitSuiteConfig,
    repo_root: Path,
    results_dir: Path,
    pdk_name: str,
    model_name: str,
    job_root: Path,
) -> list[CircuitRunResult]:
    pdk = cfg.pdk_targets[pdk_name]
    w_m, l_m = _device_geom(cfg, "inverter")
    cs = cfg.device_roles["cs_amp"]
    cl_f = float(cs["load_cap_f"])
    ac = cs["ac"]
    f0 = float(ac["f_start_hz"])
    f1 = min(float(ac["f_stop_hz"]), 1e9)
    vdd = pdk.vdd

    ref_dir = job_root / "golden" / pdk_name / "cs_amp"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_sp = ref_dir / "ac.spice"
    ref_csv = ref_dir / "ac.txt"
    write_cs_amp_bsim(
        path=ref_sp,
        pdk=pdk,
        vdd=vdd,
        cl_f=cl_f,
        f_start=f0,
        f_stop=f1,
        out_csv=ref_csv,
    )
    _run_ngspice(ref_sp, ref_dir)

    nmos_m, pmos_m, n_card, p_card = _load_mos_cards(
        results_dir=results_dir,
        repo_root=repo_root,
        model_name=model_name,
        pdk=pdk_name,
        width_m=w_m,
        length_m=l_m,
    )
    acm_dir = job_root / model_name / pdk_name / "cs_amp"
    acm_dir.mkdir(parents=True, exist_ok=True)
    acm_sp = acm_dir / "ac.spice"
    acm_csv = acm_dir / "ac.txt"
    write_cs_amp_acm(
        path=acm_sp,
        pdk=pdk,
        nmos_model=nmos_m,
        pmos_model=pmos_m,
        nmos_card=n_card,
        pmos_card=p_card,
        vdd=vdd,
        cl_f=cl_f,
        f_start=f0,
        f_stop=f1,
        out_csv=acm_csv,
    )
    _run_ngspice(acm_sp, acm_dir)
    metrics = ac_gain_db_rmse(ref_csv, acm_csv)
    return [
        CircuitRunResult(
            circuit="cs_amp",
            pdk=pdk_name,
            model=model_name,
            analysis="ac",
            metrics=metrics,
            job_dir=acm_dir,
        )
    ]


def run_circuit_suite(
    *,
    cfg: CircuitSuiteConfig,
    repo_root: Path,
    results_dir: Path,
    circuits: tuple[str, ...] | None = None,
    models: tuple[str, ...] | None = None,
    pdks: tuple[str, ...] | None = None,
) -> list[CircuitRunResult]:
    """Execute selected circuits and return metric rows."""
    job_root = results_dir / "circuits" / "adornes"
    job_root.mkdir(parents=True, exist_ok=True)
    selected_circuits = circuits or tuple(cfg.circuits.keys())
    selected_models = models or cfg.models
    selected_pdks = pdks or cfg.pdks
    rows: list[CircuitRunResult] = []
    runners = {
        "inverter": _run_inverter,
        "ring_osc": _run_ring_osc,
        "sbcs": _run_sbcs,
        "cs_amp": _run_cs_amp,
    }
    for circuit in selected_circuits:
        if circuit not in runners:
            raise ValueError(f"unsupported circuit {circuit!r}")
        for pdk_name in selected_pdks:
            for model_name in selected_models:
                rows.extend(
                    runners[circuit](
                        cfg=cfg,
                        repo_root=repo_root,
                        results_dir=results_dir,
                        pdk_name=pdk_name,
                        model_name=model_name,
                        job_root=job_root,
                    )
                )
    summary = [
        {
            "circuit": r.circuit,
            "pdk": r.pdk,
            "model": r.model,
            "analysis": r.analysis,
            "metrics": dict(r.metrics),
            "job_dir": str(r.job_dir),
        }
        for r in rows
    ]
    out_path = job_root / "summary.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n")
    _write_summary_md(job_root, rows, cfg)
    return rows


def _write_summary_md(
    job_root: Path,
    rows: list[CircuitRunResult],
    cfg: CircuitSuiteConfig,
) -> None:
    lines = [
        "# Adornes circuit benchmark",
        "",
        f"Config: `{cfg.path}`",
        "",
        "## Results",
        "",
        "| Circuit | PDK | Model | VDD (V) | Key metric |",
        "|---------|-----|-------|---------|------------|",
    ]
    for r in rows:
        m = r.metrics
        vdd = m.get("vdd_v", "")
        if r.circuit == "inverter":
            key = f"vout_rmse={m.get('vout_rmse', float('nan')):.4g}"
        elif r.circuit == "ring_osc":
            f_bsim = m.get("f_osc_hz_bsim", float("nan"))
            f_acm = m.get("f_osc_hz_acm", float("nan"))
            key = (
                f"f_ratio={m.get('f_osc_ratio', float('nan')):.3f} "
                f"(BSIM={f_bsim/1e6:.3g} MHz, ACM={f_acm/1e6:.3g} MHz)"
            )
        elif r.circuit == "cs_amp":
            key = f"gain_db_rmse={m.get('gain_db_rmse', float('nan')):.3f}"
        else:
            key = str({k: v for k, v in m.items() if k.endswith("_rel_err")})
        lines.append(
            f"| {r.circuit} | {r.pdk} | {r.model} | {vdd} | {key} |"
        )

    paper = cfg.paper_reference_targets
    ring = paper.get("ring_osc_f_osc_mhz")
    if ring:
        lines.extend(
            [
                "",
                "## Paper reference (45 nm BSIM vs 4PM, Table 4–5)",
                "",
                "| VDD (mV) | BSIM (MHz) | 4PM (MHz) |",
                "|----------|------------|-----------|",
            ]
        )
        for label, vals in ring.items():
            mv = label.replace("_mV", "")
            lines.append(
                f"| {mv} | {vals.get('bsim', '')} | {vals.get('4pm', '')} |"
            )
    (job_root / "CIRCUITS.md").write_text("\n".join(lines) + "\n")


__all__ = ["CircuitRunResult", "run_circuit_suite"]
