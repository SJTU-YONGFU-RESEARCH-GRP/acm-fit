"""SPICE netlist generation for Adornes circuit benchmark."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from acm_circuit.config import PdkCircuitTarget
from acm_opt.models import ModelSpec
from acm_opt.params import format_spice_instance_params


def _bsim_mos(
    name: str,
    d: str,
    g: str,
    s: str,
    b: str,
    model_name: str,
    *,
    width_m: float,
    length_m: float,
    m: int = 1,
) -> str:
    """Instantiate one BSIM device with W/L override."""
    w = width_m * 1e6
    l = length_m * 1e6
    if model_name.startswith("sky130"):
        return f"{name} {d} {g} {s} {b} {model_name} w={w:.6g} l={l:.6g}"
    return f"{name} {d} {g} {s} {b} {model_name} W={w:.6g}u L={l:.6g}u m={m}"


def _acm_model_lines(nmos_model: ModelSpec, pmos_model: ModelSpec) -> str:
    if nmos_model.spice_model == pmos_model.spice_model:
        return f".model {nmos_model.spice_model} {nmos_model.module_name}"
    return (
        f".model {nmos_model.spice_model} {nmos_model.module_name}\n"
        f".model {pmos_model.spice_model} {pmos_model.module_name}"
    )


def _acm_pre_osdi(nmos_model: ModelSpec, pmos_model: ModelSpec) -> str:
    osdi_n = nmos_model.osdi_path.resolve()
    osdi_p = pmos_model.osdi_path.resolve()
    if osdi_n == osdi_p:
        return f"pre_osdi {osdi_n}"
    return f"pre_osdi {osdi_n}\npre_osdi {osdi_p}"


def _acm_instance_name(name: str) -> str:
    """ngspice OSDI MOSFET instances must use an ``N*`` device name."""
    if not name.startswith("N"):
        return f"N{name}"
    return name


def _acm_mos(
    name: str,
    d: str,
    g: str,
    s: str,
    b: str,
    model: ModelSpec,
    card: Mapping[str, float],
    *,
    width_m: float,
    length_m: float,
    m: int = 1,
) -> str:
    body = format_spice_instance_params(
        model,
        {**card, "W": width_m, "L": length_m},
        width_m=width_m,
        length_m=length_m,
    )
    if m != 1:
        body = body.replace("m=1", f"m={int(m)}")
    inst = _acm_instance_name(name)
    return f"{inst} {d} {g} {s} {b} {model.spice_model} {body}"


def write_inverter_vtc_bsim(
    *,
    path: Path,
    pdk: PdkCircuitTarget,
    width_m: float,
    length_m: float,
    vdd: float,
    v_step: float,
    out_csv: Path,
) -> None:
    """CMOS inverter DC VTC — BSIM golden."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""* inverter VTC BSIM {pdk.name} VDD={vdd}
{pdk.ngspice_section}
VDD vdd 0 DC {vdd}
VIN in 0 0
{_bsim_mos("XMN", "out", "in", "0", "0", pdk.nfet, width_m=width_m, length_m=length_m)}
{_bsim_mos("XMP", "out", "in", "vdd", "vdd", pdk.pfet, width_m=width_m, length_m=length_m)}
.control
dc VIN 0 {vdd} {v_step}
set wr_singlescale
wrdata {out_csv.resolve()} v(in) v(out)
.endc
.end
"""
    )


def write_inverter_vtc_acm(
    *,
    path: Path,
    pdk: PdkCircuitTarget,
    nmos_model: ModelSpec,
    pmos_model: ModelSpec,
    nmos_card: Mapping[str, float],
    pmos_card: Mapping[str, float],
    width_m: float,
    length_m: float,
    vdd: float,
    v_step: float,
    out_csv: Path,
) -> None:
    """CMOS inverter DC VTC — ACM candidate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    model_lines = _acm_model_lines(nmos_model, pmos_model)
    pre_osdi = _acm_pre_osdi(nmos_model, pmos_model)
    path.write_text(
        f"""* inverter VTC ACM {pdk.name} VDD={vdd}
{model_lines}
VDD vdd 0 DC {vdd}
VIN in 0 0
{_acm_mos("N1", "out", "in", "0", "0", nmos_model, nmos_card, width_m=width_m, length_m=length_m)}
{_acm_mos("N2", "out", "in", "vdd", "vdd", pmos_model, pmos_card, width_m=width_m, length_m=length_m)}
.control
{pre_osdi}
dc VIN 0 {vdd} {v_step}
set wr_singlescale
wrdata {out_csv.resolve()} v(in) v(out)
.endc
.end
"""
    )


def _ring_stage_bsim(
    idx: int,
    pdk: PdkCircuitTarget,
    width_m: float,
    length_m: float,
    prev: str,
    nxt: str,
) -> str:
    inv = f"xinv{idx}"
    return f"""* stage {idx}
VDD{idx} vdd 0 DC {{vdd}}
{_bsim_mos(f"XN{idx}", nxt, prev, "0", "0", pdk.nfet, width_m=width_m, length_m=length_m)}
{_bsim_mos(f"XP{idx}", nxt, prev, "vdd", "vdd", pdk.pfet, width_m=width_m, length_m=length_m)}
"""


def _ring_stage_acm(
    idx: int,
    nmos_model: ModelSpec,
    pmos_model: ModelSpec,
    nmos_card: Mapping[str, float],
    pmos_card: Mapping[str, float],
    width_m: float,
    length_m: float,
    prev: str,
    nxt: str,
) -> str:
    return f"""* stage {idx}
{_acm_mos(f"N{2 * idx - 1}", nxt, prev, "0", "0", nmos_model, nmos_card, width_m=width_m, length_m=length_m)}
{_acm_mos(f"N{2 * idx}", nxt, prev, "vdd", "vdd", pmos_model, pmos_card, width_m=width_m, length_m=length_m)}
"""


def write_ring_osc_bsim(
    *,
    path: Path,
    pdk: PdkCircuitTarget,
    width_m: float,
    length_m: float,
    stages: int,
    vdd: float,
    t_stop_s: float,
    out_csv: Path,
) -> None:
    """Odd-stage ring oscillator transient — BSIM golden."""
    nodes = [f"n{i}" for i in range(stages)]
    body: list[str] = [
        f"* ring oscillator BSIM {pdk.name} stages={stages} VDD={vdd}",
        pdk.ngspice_section,
        f"VDD vdd 0 DC {vdd}",
        f"IC {nodes[0]} 0 0.01",
    ]
    for i in range(stages):
        prev = nodes[(i - 1) % stages]
        nxt = nodes[i]
        body.append(
            _bsim_mos(f"XN{i + 1}", nxt, prev, "0", "0", pdk.nfet, width_m=width_m, length_m=length_m)
        )
        body.append(
            _bsim_mos(f"XP{i + 1}", nxt, prev, "vdd", "vdd", pdk.pfet, width_m=width_m, length_m=length_m)
        )
    probe = nodes[stages // 2]
    body.append(
        f""".control
tran {t_stop_s / 2000:.3e} {t_stop_s:.3e} uic
wrdata {out_csv.resolve()} v({probe})
.endc
.end
"""
    )
    path.write_text("\n".join(body) + "\n")


def write_ring_osc_acm(
    *,
    path: Path,
    pdk: PdkCircuitTarget,
    nmos_model: ModelSpec,
    pmos_model: ModelSpec,
    nmos_card: Mapping[str, float],
    pmos_card: Mapping[str, float],
    width_m: float,
    length_m: float,
    stages: int,
    vdd: float,
    t_stop_s: float,
    out_csv: Path,
) -> None:
    """Odd-stage ring oscillator transient — ACM."""
    nodes = [f"n{i}" for i in range(stages)]
    body: list[str] = [
        f"* ring oscillator ACM {pdk.name} stages={stages} VDD={vdd}",
        _acm_model_lines(nmos_model, pmos_model),
        f"VDD vdd 0 DC {vdd}",
        f"IC {nodes[0]} 0 0.01",
    ]
    for i in range(stages):
        prev = nodes[(i - 1) % stages]
        nxt = nodes[i]
        body.append(
            _ring_stage_acm(
                i + 1,
                nmos_model,
                pmos_model,
                nmos_card,
                pmos_card,
                width_m,
                length_m,
                prev,
                nxt,
            )
        )
    probe = nodes[stages // 2]
    pre_osdi = _acm_pre_osdi(nmos_model, pmos_model)
    body.append(
        f""".control
{pre_osdi}
tran {t_stop_s / 2000:.3e} {t_stop_s:.3e} uic
wrdata {out_csv.resolve()} v({probe})
.endc
.end
"""
    )
    path.write_text("\n".join(body) + "\n")


def write_sbcs_bsim(
    *,
    path: Path,
    pdk: PdkCircuitTarget,
    vdd: float,
    out_meas: Path,
) -> None:
    """Self-biased current source — simplified 4-transistor ULV bias (BSIM)."""
    w_n, l_n = 0.5e-6, 2.0e-6
    w_p, l_p = 4.0e-6, 2.0e-6
    path.write_text(
        f"""* SBCS simplified BSIM {pdk.name}
{pdk.ngspice_section}
VDD vdd 0 DC {vdd}
{_bsim_mos("MN1", "nb", "nb", "0", "0", pdk.nfet, width_m=w_n, length_m=l_n, m=4)}
{_bsim_mos("MN2", "out", "nb", "0", "0", pdk.nfet, width_m=1e-5, length_m=l_n)}
{_bsim_mos("MP1", "pb", "pb", "vdd", "vdd", pdk.pfet, width_m=w_p, length_m=l_p)}
{_bsim_mos("MP2", "out", "pb", "vdd", "vdd", pdk.pfet, width_m=0.5e-6, length_m=l_p)}
RLOAD out 0 1e9
.control
op
echo "@sbcs_vout" > {out_meas.resolve()}
print v(out) i(RLOAD) > {out_meas.resolve()}
.endc
.end
"""
    )


def write_sbcs_acm(
    *,
    path: Path,
    pdk: PdkCircuitTarget,
    nmos_model: ModelSpec,
    pmos_model: ModelSpec,
    nmos_card: Mapping[str, float],
    pmos_card: Mapping[str, float],
    vdd: float,
    out_meas: Path,
) -> None:
    w_n, l_n = 0.5e-6, 2.0e-6
    w_p, l_p = 4.0e-6, 2.0e-6
    pre_osdi = _acm_pre_osdi(nmos_model, pmos_model)
    path.write_text(
        f"""* SBCS simplified ACM {pdk.name}
{_acm_model_lines(nmos_model, pmos_model)}
VDD vdd 0 DC {vdd}
{_acm_mos("N1", "nb", "nb", "0", "0", nmos_model, nmos_card, width_m=w_n, length_m=l_n, m=4)}
{_acm_mos("N2", "out", "nb", "0", "0", nmos_model, nmos_card, width_m=1e-5, length_m=l_n)}
{_acm_mos("N3", "pb", "pb", "vdd", "vdd", pmos_model, pmos_card, width_m=w_p, length_m=l_p)}
{_acm_mos("N4", "out", "pb", "vdd", "vdd", pmos_model, pmos_card, width_m=0.5e-6, length_m=l_p)}
RLOAD out 0 1e9
.control
{pre_osdi}
op
print v(out) i(RLOAD) > {out_meas.resolve()}
.endc
.end
"""
    )


def write_cs_amp_bsim(
    *,
    path: Path,
    pdk: PdkCircuitTarget,
    vdd: float,
    cl_f: float,
    f_start: float,
    f_stop: float,
    out_csv: Path,
) -> None:
    w_n, l_n = 2.0e-6, 1.8e-7
    w_p, l_p = 0.5e-6, 2.0e-6
    path.write_text(
        f"""* CS amplifier BSIM {pdk.name}
{pdk.ngspice_section}
VDD vdd 0 DC {vdd}
VIN in 0 DC {vdd * 0.55} AC 1
VG_BIAS bias 0 DC {vdd * 0.4}
{_bsim_mos("MN1", "out", "in", "0", "0", pdk.nfet, width_m=w_n, length_m=l_n)}
{_bsim_mos("MP1", "out", "bias", "vdd", "vdd", pdk.pfet, width_m=w_p, length_m=l_p)}
CLOAD out 0 {cl_f:.3e}
.control
ac dec 10 {f_start:.3e} {f_stop:.3e}
wrdata {out_csv.resolve()} frequency vm(out)
.endc
.end
"""
    )


def write_cs_amp_acm(
    *,
    path: Path,
    pdk: PdkCircuitTarget,
    nmos_model: ModelSpec,
    pmos_model: ModelSpec,
    nmos_card: Mapping[str, float],
    pmos_card: Mapping[str, float],
    vdd: float,
    cl_f: float,
    f_start: float,
    f_stop: float,
    out_csv: Path,
) -> None:
    w_n, l_n = 2.0e-6, 1.8e-7
    w_p, l_p = 0.5e-6, 2.0e-6
    pre_osdi = _acm_pre_osdi(nmos_model, pmos_model)
    path.write_text(
        f"""* CS amplifier ACM {pdk.name}
{_acm_model_lines(nmos_model, pmos_model)}
VDD vdd 0 DC {vdd}
VIN in 0 DC {vdd * 0.55} AC 1
VG_BIAS bias 0 DC {vdd * 0.4}
{_acm_mos("N1", "out", "in", "0", "0", nmos_model, nmos_card, width_m=w_n, length_m=l_n)}
{_acm_mos("N2", "out", "bias", "vdd", "vdd", pmos_model, pmos_card, width_m=w_p, length_m=l_p)}
CLOAD out 0 {cl_f:.3e}
.control
{pre_osdi}
ac dec 10 {f_start:.3e} {f_stop:.3e}
wrdata {out_csv.resolve()} frequency vm(out)
.endc
.end
"""
    )


__all__ = [
    "write_inverter_vtc_bsim",
    "write_inverter_vtc_acm",
    "write_ring_osc_bsim",
    "write_ring_osc_acm",
    "write_sbcs_bsim",
    "write_sbcs_acm",
    "write_cs_amp_bsim",
    "write_cs_amp_acm",
]
