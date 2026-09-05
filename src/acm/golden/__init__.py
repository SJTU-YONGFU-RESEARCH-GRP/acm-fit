"""Golden I-V corpus generation and loading for ACM DC fitting."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

_TIME_RE = re.compile(r"^ACM_TIME\s+([0-9.eE+-]+)\s+(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class GoldenTarget:
    """One PDK device target for golden I-V capture."""

    name: str
    vdd: float
    width_m: float
    length_m: float
    ngspice_section: str
    ref_device: str
    polarity: str = "nmos"
    base_pdk: str | None = None
    corner: str | None = None
    data_only: bool = False


@dataclass(frozen=True)
class GoldenCurve:
    """One Id-Vg curve at fixed VDS."""

    vds: float
    vg: np.ndarray
    id_ref: np.ndarray


@dataclass(frozen=True)
class GoldenDevice:
    """Golden I-V corpus for one PDK device."""

    pdk: str
    vdd: float
    width_m: float
    length_m: float
    curves: tuple[GoldenCurve, ...]
    meta: Mapping[str, Any]
    base_pdk: str | None = None
    corner: str | None = None


def _expand(template: str, env: Mapping[str, str], repo_root: Path) -> str:
    """Expand ``${VAR}`` placeholders from target env and ``os.environ``."""
    placeholders = set(re.findall(r"\$\{([^}]+)\}", template))
    merged: dict[str, str] = dict(env)
    for key in placeholders:
        if key in os.environ and os.environ[key]:
            merged[key] = os.environ[key]
    out = template
    for key in placeholders:
        if key not in merged or not merged[key]:
            raise ValueError(
                f"unresolved placeholder ${{{key}}} in {template!r}; "
                f"set {key} in config/pdk_env.local.json or export it"
            )
        value = merged[key]
        path_value = value
        if value and not Path(value).is_absolute() and "${" not in value:
            path_value = str((repo_root / value).resolve())
        out = out.replace(f"${{{key}}}", path_value)
    return out


def _flatten_golden_targets(raw_targets: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Expand optional per-PDK ``corners`` into ``{pdk}_{corner}`` target entries."""
    flat: dict[str, dict[str, Any]] = {}
    for pdk_name, entry in raw_targets.items():
        corners = entry.get("corners")
        if corners is None:
            if not entry.get("data_only") and "ngspice_section" not in entry:
                raise ValueError(
                    f"target {pdk_name!r}: ngspice_section required when corners absent "
                    "(or set data_only=true)"
                )
            flat[pdk_name] = dict(entry)
            continue
        if not isinstance(corners, Mapping):
            raise ValueError(f"target {pdk_name!r}: corners must be an object")
        shared = {
            k: v
            for k, v in entry.items()
            if k not in {"corners", "ngspice_section"}
        }
        for corner_id, corner_entry in corners.items():
            if not isinstance(corner_entry, Mapping):
                raise ValueError(
                    f"target {pdk_name!r} corner {corner_id!r}: must be an object"
                )
            merged = {**shared, **corner_entry}
            if "ngspice_section" not in merged:
                raise ValueError(
                    f"target {pdk_name!r} corner {corner_id!r}: "
                    "missing ngspice_section"
                )
            target_name = f"{pdk_name}_{corner_id}"
            merged["corner"] = str(corner_id)
            merged["pdk"] = str(pdk_name)
            flat[target_name] = merged
    return flat


def load_golden_config(path: Path, repo_root: Path) -> dict[str, Any]:
    """Load and expand golden-suite JSON config."""
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = json.loads(path.read_text())
    targets: dict[str, GoldenTarget] = {}
    for name, entry in _flatten_golden_targets(raw["targets"]).items():
        env = {k: str(v) for k, v in entry.get("env", {}).items()}
        polarity = str(entry.get("polarity", "nmos"))
        if polarity not in {"nmos", "pmos"}:
            raise ValueError(f"target {name!r}: polarity must be nmos or pmos, got {polarity!r}")
        data_only = bool(entry.get("data_only", False))
        if data_only:
            if entry.get("ngspice_section") or entry.get("ref_device"):
                raise ValueError(
                    f"target {name!r}: data_only targets must not set "
                    "ngspice_section or ref_device"
                )
            section = ""
            ref_device = ""
        else:
            if "ngspice_section" not in entry or "ref_device" not in entry:
                raise ValueError(
                    f"target {name!r}: ngspice_section and ref_device required "
                    "(or set data_only=true for user-supplied golden CSVs)"
                )
            section = _expand(entry["ngspice_section"], env, repo_root)
            ref_device = str(entry["ref_device"])
        targets[name] = GoldenTarget(
            name=name,
            vdd=float(entry["vdd"]),
            width_m=float(entry["width_m"]),
            length_m=float(entry["length_m"]),
            ngspice_section=section,
            ref_device=ref_device,
            polarity=polarity,
            base_pdk=str(entry["pdk"]) if entry.get("pdk") is not None else None,
            corner=str(entry["corner"]) if entry.get("corner") is not None else None,
            data_only=data_only,
        )
    raw["_targets"] = targets
    return raw


def _run_ngspice(netlist: Path, cwd: Path) -> None:
    """Run ngspice with absolute netlist path."""
    time_bin = Path("/usr/bin/time")
    proc = subprocess.run(
        [
            str(time_bin),
            "-f",
            "ACM_TIME %e %M",
            "ngspice",
            "-b",
            str(netlist.resolve()),
        ],
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    log = netlist.with_suffix(".log")
    log.write_text((proc.stdout or "") + "\n" + (proc.stderr or ""))
    if proc.returncode != 0:
        raise RuntimeError(f"ngspice failed for {netlist}; see {log}")


def capture_golden_iv(
    *,
    target: GoldenTarget,
    output_dir: Path,
    vg_start: float,
    vg_step: float,
    vds_fractions: list[float],
) -> GoldenDevice:
    """Simulate PDK BSIM Id-Vg curves and write CSV + meta.

    Args:
        target: PDK device description.
        output_dir: Directory for this device's golden files.
        vg_start: Gate sweep start.
        vg_step: Gate sweep step.
        vds_fractions: VDS = fraction * VDD for each curve.

    Returns:
        Loaded :class:`GoldenDevice`.
    """
    if target.data_only:
        raise ValueError(
            f"target {target.name!r} is data_only; supply golden CSVs under "
            f"{output_dir} and run with --skip-golden"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    spiceinit = output_dir / ".spiceinit"
    if not spiceinit.exists():
        spiceinit.write_text("set ngbehavior=hs\n")

    curves: list[GoldenCurve] = []
    polarity = target.polarity
    vdd = float(target.vdd)
    for frac in vds_fractions:
        vds_abs = float(frac) * vdd
        if polarity == "nmos":
            vg_gate_start = float(vg_start)
            vg_gate_stop = vdd
            vg_gate_step = float(vg_step)
            bias = f"""VG1 g1 0 DC {vg_gate_start}
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vds_abs}"""
        else:
            # Source/bulk at VDD; gate sweeps VDD→0 so |Vgs| covers 0→VDD.
            # Storing negative gate or 0→−VDD keeps the device in strong
            # inversion for the whole sweep and breaks VT0 extraction.
            vg_gate_start = vdd
            vg_gate_stop = 0.0
            vg_gate_step = -abs(float(vg_step))
            bias = f"""VDD vdd 0 DC {vdd}
VG1 g1 0 DC {vg_gate_start}
VS1 s1 vdd DC 0
VB1 b1 vdd DC 0
VD1 d1 0 DC {vdd - vds_abs}"""
        tag = f"idvg_vds_{vds_abs:.4g}".replace(".", "p")
        if polarity == "pmos":
            tag = f"pmos_{tag}"
        out_txt = (output_dir / f"{tag}.txt").resolve()
        netlist = output_dir / f"{tag}.spice"
        netlist.write_text(
            f"""* golden I-V {target.name} polarity={polarity} |VDS|={vds_abs}
{target.ngspice_section}
{bias}
{target.ref_device}
.control
dc VG1 {vg_gate_start} {vg_gate_stop} {vg_gate_step}
wrdata {out_txt} abs(i(VS1))
.endc
.end
"""
        )
        _run_ngspice(netlist, cwd=output_dir)
        raw = np.loadtxt(out_txt)
        vg_gate = raw[:, 0]
        id_ref = raw[:, 1]
        # Store |Vgs| on the same 0→VDD axis used for NMOS / ACM magnitude fit.
        if polarity == "pmos":
            vg = vdd - vg_gate
        else:
            vg = vg_gate
        _assert_idvg_covers_threshold(vg, id_ref, polarity=polarity, vdd=vdd)
        csv_path = output_dir / f"{tag}.csv"
        with csv_path.open("w") as fh:
            fh.write("vg,id_ref\n")
            for x, y in zip(vg, id_ref):
                fh.write(f"{x:.10g},{y:.10g}\n")
        # Keep only durable golden tables; drop sim scratch.
        for scratch in (netlist, out_txt, netlist.with_suffix(".log")):
            scratch.unlink(missing_ok=True)
        curves.append(GoldenCurve(vds=vds_abs, vg=vg, id_ref=id_ref))

    meta = {
        "pdk": target.name,
        "vdd": target.vdd,
        "width_m": target.width_m,
        "length_m": target.length_m,
        "polarity": polarity,
        "vg_start": vg_start,
        "vg_step": vg_step,
        "vds_list": [c.vds for c in curves],
        "n_points_per_curve": int(len(curves[0].vg)),
        "source": "pdk_bsim_ngspice",
        "role": "golden_iv_for_acm_dc_fit",
    }
    if target.base_pdk is not None:
        meta["base_pdk"] = target.base_pdk
    if target.corner is not None:
        meta["corner"] = target.corner
    (output_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    spiceinit.unlink(missing_ok=True)
    return GoldenDevice(
        pdk=target.name,
        vdd=target.vdd,
        width_m=target.width_m,
        length_m=target.length_m,
        curves=tuple(curves),
        meta=meta,
        base_pdk=target.base_pdk,
        corner=target.corner,
    )


def _assert_idvg_covers_threshold(
    vg: np.ndarray,
    id_ref: np.ndarray,
    *,
    polarity: str,
    vdd: float,
) -> None:
    """Fail fast if an Id–Vg sweep never leaves strong inversion / cutoff."""
    if vg.size < 3:
        raise ValueError(f"{polarity} Id-Vg has too few points ({vg.size})")
    order = np.argsort(vg)
    vg_s = np.asarray(vg, dtype=float)[order]
    id_s = np.abs(np.asarray(id_ref, dtype=float)[order])
    if float(vg_s[0]) < -1.0e-9 or float(vg_s[-1]) > float(vdd) + 1.0e-6:
        raise ValueError(
            f"{polarity} |Vgs| axis must span ~[0, VDD]; "
            f"got [{vg_s[0]:.4g}, {vg_s[-1]:.4g}] with VDD={vdd:.4g}"
        )
    id_lo = float(id_s[0])
    id_hi = float(id_s[-1])
    if not (id_hi > 10.0 * max(id_lo, 1.0e-18)):
        raise ValueError(
            f"{polarity} Id-Vg does not cover threshold: "
            f"|Id|(|Vgs|≈0)={id_lo:.4e}, |Id|(|Vgs|≈VDD)={id_hi:.4e} "
            "(expected on-current ≫ off-current; check PMOS gate bias)"
        )


def validate_golden_device(device_dir: Path) -> GoldenDevice:
    """Load and validate one golden device directory (raises on schema errors)."""
    return load_golden_device(device_dir)


def load_golden_device(device_dir: Path) -> GoldenDevice:
    """Load golden I-V corpus from a device directory."""
    meta_path = device_dir / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"missing {meta_path}")
    meta = json.loads(meta_path.read_text())
    polarity = str(meta.get("polarity", "nmos"))
    vdd = float(meta["vdd"])
    curves: list[GoldenCurve] = []
    for vds in meta["vds_list"]:
        tag = f"idvg_vds_{float(vds):.4g}".replace(".", "p")
        if polarity == "pmos":
            tag = f"pmos_{tag}"
        csv_path = device_dir / f"{tag}.csv"
        if not csv_path.is_file():
            raise FileNotFoundError(csv_path)
        raw = np.loadtxt(csv_path, delimiter=",", skiprows=1)
        vg = raw[:, 0]
        id_ref = raw[:, 1]
        _assert_idvg_covers_threshold(vg, id_ref, polarity=polarity, vdd=vdd)
        curves.append(GoldenCurve(vds=float(vds), vg=vg, id_ref=id_ref))
    return GoldenDevice(
        pdk=str(meta["pdk"]),
        vdd=vdd,
        width_m=float(meta["width_m"]),
        length_m=float(meta["length_m"]),
        curves=tuple(curves),
        meta={**meta, "polarity": polarity},
        base_pdk=str(meta["base_pdk"]) if meta.get("base_pdk") is not None else None,
        corner=str(meta["corner"]) if meta.get("corner") is not None else None,
    )


__all__ = [
    "GoldenTarget",
    "GoldenCurve",
    "GoldenDevice",
    "load_golden_config",
    "capture_golden_iv",
    "load_golden_device",
    "validate_golden_device",
]
