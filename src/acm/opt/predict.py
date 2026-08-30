"""Predict AC/noise/temp/tran/dc benches from a fitted ACM card across simulators.

ACM-only netlists are shared with the eval suite (same topology / ASCII export).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

from acm.eval.export import (
    assert_hspice_va_loaded,
    export_hspice_waveform,
    export_ngspice_waveform,
    export_spectre_waveform,
)
from acm.eval.netlists import (
    format_instance_params,
    write_acm_hspice,
    write_acm_ngspice,
    write_acm_spectre,
)
from acm.eval.config import PdkEvalConfig
from acm.eval.waveforms import ensure_hspice_va_path
from acm.opt.models import ModelSpec

_TIME_RE = re.compile(r"^ACM_TIME\s+([0-9.eE+-]+)\s+(\d+)\s*$", re.MULTILINE)

# Default analysis params when predict is used without eval_suite.json.
_DEFAULT_ANALYSIS: dict[str, dict[str, Any]] = {
    "dc": {"vg_start": 0.0, "vg_step": 0.05},
    "ac": {
        "vgs": 0.9,
        "f_start": 1.0e3,
        "f_stop": 1.0e9,
        "points_per_decade": 10,
        "rd_ohm": 1000.0,
    },
    "noise": {
        "vgs": 0.9,
        "f_start": 1.0e3,
        "f_stop": 1.0e9,
        "points_per_decade": 10,
        "rd_ohm": 1000.0,
    },
    "transient": {
        "v_low": 0.0,
        "t_rise": 1.0e-9,
        "t_fall": 1.0e-9,
        "t_pulse": 50.0e-9,
        "t_period": 100.0e-9,
        "t_stop": 200.0e-9,
        "t_step": 0.2e-9,
    },
    "temp": {"vgs": 0.9, "temps_c": [0.0, 27.0, 85.0, 125.0]},
}


def _pdk_stub(card: Mapping[str, Any]) -> PdkEvalConfig:
    """Minimal PDK geometry stub for ``format_instance_params``."""
    params = card["parameters"]
    return PdkEvalConfig(
        name=str(card["pdk"]),
        vdd=float(card["vdd"]),
        width="",
        length="",
        width_m=float(params["W"]),
        length_m=float(params["L"]),
        sections={"ngspice": ""},
        ref_devices={"ngspice": ""},
    )


def _cleanup_sim_scratch(cwd: Path) -> None:
    """Remove regenerable simulator caches/binary dumps; keep netlists and logs."""
    for path in cwd.iterdir():
        name = path.name
        if path.is_dir() and (
            name.endswith(".ahdlSimDB")
            or name.endswith(".raw")
            or name == "raw"
        ):
            shutil.rmtree(path)
            continue
        if path.is_file() and path.suffix in {
            ".tr0",
            ".ac0",
            ".sw0",
            ".st0",
            ".mt0",
            ".ic0",
            ".pa0",
            ".graph",
        }:
            path.unlink()


def _run_job(
    *,
    sim: str,
    netlist: Path,
    cwd: Path,
    analysis: str,
    hspice_hdl: Path | None,
) -> dict[str, Any]:
    """Run one predict job and export ``acm.csv`` when possible."""
    net = netlist.resolve()
    log = cwd / f"{netlist.stem}.log"
    if sim == "ngspice":
        cmd = ["/usr/bin/time", "-f", "ACM_TIME %e %M", "ngspice", "-b", str(net)]
    elif sim == "spectre":
        cmd = [
            "/usr/bin/time",
            "-f",
            "ACM_TIME %e %M",
            "spectre",
            str(net),
            "+log",
            str((cwd / f"{netlist.stem}_spectre.log").resolve()),
        ]
    elif sim == "hspice":
        cmd = [
            "/usr/bin/time",
            "-f",
            "ACM_TIME %e %M",
            "hspice",
            str(net),
            "-o",
            str((cwd / netlist.stem).resolve()),
        ]
        if hspice_hdl is not None:
            cmd.extend(["-hdl", str(hspice_hdl.resolve())])
    else:
        raise ValueError(sim)
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    log.write_text(text)
    runtime = rss = None
    match = _TIME_RE.search(text)
    if match:
        runtime = float(match.group(1))
        rss = int(match.group(2))
    ok = proc.returncode == 0
    if sim == "spectre":
        slog = cwd / f"{netlist.stem}_spectre.log"
        stext = slog.read_text(errors="ignore") if slog.is_file() else text
        if "Error found by spectre" in stext or "terminated prematurely" in stext:
            ok = False
        if "completes with 0 errors" in stext:
            ok = True
    if sim == "hspice":
        lis = cwd / f"{netlist.stem}.lis"
        lis_text = lis.read_text(errors="ignore") if lis.is_file() else ""
        if "Unable to checkout" in lis_text or "No valid input file" in text:
            ok = False
        elif "job concluded" in lis_text:
            ok = True
            try:
                assert_hspice_va_loaded(lis)
            except RuntimeError:
                ok = False
    if ok:
        try:
            acm_csv = cwd / "acm.csv"
            if sim == "ngspice":
                export_ngspice_waveform(
                    analysis=analysis,
                    raw_path=cwd / f"{analysis}_out.txt",
                    csv_path=acm_csv,
                )
            elif sim == "spectre":
                export_spectre_waveform(
                    analysis=analysis,
                    job_dir=cwd,
                    netlist_stem=analysis,
                    csv_path=acm_csv,
                )
            else:
                export_hspice_waveform(
                    analysis=analysis,
                    lis_path=cwd / f"{analysis}.lis",
                    csv_path=acm_csv,
                )
        except (ValueError, FileNotFoundError, OSError, RuntimeError):
            ok = False
        _cleanup_sim_scratch(cwd)
    return {
        "simulator": sim,
        "analysis": analysis,
        "ok": ok,
        "runtime_s": runtime,
        "peak_rss_kb": rss,
        "log": str(log),
    }


def run_predict_benches(
    *,
    model: ModelSpec,
    card: Mapping[str, Any],
    output_dir: Path,
    analyses: tuple[str, ...],
    simulators: tuple[str, ...],
    jobs: int = 4,
    analysis_params: Mapping[str, Mapping[str, Any]] | None = None,
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Generate and run predict benches for one fitted card."""
    if "vdd" not in card or "pdk" not in card or "model" not in card:
        raise ValueError(
            "fitted card missing required fields "
            f"{sorted({'vdd', 'pdk', 'model'} - set(card))}"
        )
    params_map = {k: float(v) for k, v in card["parameters"].items()}
    pdk = _pdk_stub(card)
    params = format_instance_params(model, params_map, pdk)
    vdd = float(card["vdd"])
    aparams = analysis_params or _DEFAULT_ANALYSIS
    root = repo_root or Path(__file__).resolve().parents[2]
    hspice_hdl = (
        ensure_hspice_va_path(model.va_path, root / "work" / "hspice_va")
        if "hspice" in simulators
        else None
    )

    planned: list[tuple[str, Path, Path, str]] = []
    for sim in simulators:
        for analysis in analyses:
            if analysis not in aparams:
                raise ValueError(f"missing analysis params for {analysis!r}")
            job_dir = output_dir / sim / analysis
            job_dir.mkdir(parents=True, exist_ok=True)
            (job_dir / ".spiceinit").write_text("set ngbehavior=hs\n")
            title = f"predict {model.name} {analysis}"
            if sim == "ngspice":
                net = job_dir / f"{analysis}.spice"
                write_acm_ngspice(
                    path=net,
                    title=title,
                    model=model,
                    params=params,
                    osdi=model.osdi_path.resolve(),
                    analysis=analysis,
                    analysis_params=aparams[analysis],
                    vdd=vdd,
                    out_txt=(job_dir / f"{analysis}_out.txt").resolve(),
                )
            elif sim == "spectre":
                net = job_dir / f"{analysis}.scs"
                write_acm_spectre(
                    path=net,
                    title=title,
                    model=model,
                    params=params,
                    va_path=model.va_path.resolve(),
                    analysis=analysis,
                    analysis_params=aparams[analysis],
                    vdd=vdd,
                )
            elif sim == "hspice":
                net = job_dir / f"{analysis}.sp"
                write_acm_hspice(
                    path=net,
                    title=title,
                    model=model,
                    params=params,
                    analysis=analysis,
                    analysis_params=aparams[analysis],
                    vdd=vdd,
                )
            else:
                raise ValueError(sim)
            planned.append((sim, net, job_dir, analysis))

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futs = {
            pool.submit(
                _run_job,
                sim=sim,
                netlist=net,
                cwd=job_dir,
                analysis=analysis,
                hspice_hdl=hspice_hdl,
            ): (sim, net)
            for sim, net, job_dir, analysis in planned
        }
        for fut in as_completed(futs):
            row = fut.result()
            row["pdk"] = card["pdk"]
            row["model"] = card["model"]
            row["log"] = str(Path(row["log"]).resolve())
            results.append(row)
    results.sort(key=lambda r: (str(r["simulator"]), str(r["analysis"])))
    return results


__all__ = ["run_predict_benches"]
