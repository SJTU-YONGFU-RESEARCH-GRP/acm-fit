"""ACM-only and ngspice PDK-BSIM reference netlist emitters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from acm.opt.models import ModelSpec

from .config import PdkEvalConfig


def format_instance_params(
    model: ModelSpec,
    card: Mapping[str, float],
    pdk: PdkEvalConfig,
) -> str:
    """Format ACM instance parameters for SPICE netlists."""
    from acm.opt.params import format_spice_instance_params

    return format_spice_instance_params(
        model,
        card,
        width_m=pdk.width_m,
        length_m=pdk.length_m,
    )


def _rd(analysis_params: Mapping[str, Any]) -> float:
    """Require positive drain load resistance for AC/noise."""
    rd_ohm = float(analysis_params["rd_ohm"])
    if rd_ohm <= 0.0:
        raise ValueError(f"rd_ohm must be > 0, got {rd_ohm}")
    return rd_ohm


def write_bsim_ref_ngspice(
    *,
    path: Path,
    title: str,
    pdk: PdkEvalConfig,
    analysis: str,
    analysis_params: Mapping[str, Any],
    out_txt: Path,
) -> None:
    """Write PDK-BSIM-only ngspice netlist (golden reference capture)."""
    vdd = pdk.vdd
    section = pdk.sections["ngspice"]
    ref = pdk.ref_devices["ngspice"]
    if analysis == "dc":
        vg0 = float(analysis_params["vg_start"])
        vg_step = float(analysis_params["vg_step"])
        body = f"""* {title}
{section}
VG1 g1 0 DC 0
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vdd}
{ref}
.control
dc VG1 {vg0} {vdd} {vg_step}
let id = abs(i(VS1))
wrdata {out_txt} id
.endc
.end
"""
    elif analysis == "ac":
        vgs = float(analysis_params["vgs"])
        f0 = float(analysis_params["f_start"])
        f1 = float(analysis_params["f_stop"])
        nd = int(analysis_params["points_per_decade"])
        rd = _rd(analysis_params)
        body = f"""* {title}
{section}
VG1 g1 0 DC {vgs} AC 1
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VVDD vdd 0 DC {vdd}
RD1 vdd d1 {rd}
{ref}
.control
ac dec {nd} {f0} {f1}
wrdata {out_txt} vm(d1)
.endc
.end
"""
    elif analysis == "noise":
        vgs = float(analysis_params["vgs"])
        f0 = float(analysis_params["f_start"])
        f1 = float(analysis_params["f_stop"])
        nd = int(analysis_params["points_per_decade"])
        rd = _rd(analysis_params)
        body = f"""* {title}
{section}
VG1 g1 0 DC {vgs} AC 1
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VVDD vdd 0 DC {vdd}
RD1 vdd d1 {rd}
{ref}
.control
noise v(d1) VG1 dec {nd} {f0} {f1}
setplot noise1
wrdata {out_txt} onoise_spectrum
.endc
.end
"""
    elif analysis == "transient":
        v_low = float(analysis_params["v_low"])
        tr = float(analysis_params["t_rise"])
        tf = float(analysis_params["t_fall"])
        tp = float(analysis_params["t_pulse"])
        tper = float(analysis_params["t_period"])
        tstop = float(analysis_params["t_stop"])
        tstep = float(analysis_params["t_step"])
        body = f"""* {title}
{section}
VG1 g1 0 PULSE({v_low} {vdd} 0 {tr} {tf} {tp} {tper})
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vdd}
{ref}
.control
tran {tstep} {tstop}
let id = abs(i(VS1))
wrdata {out_txt} id
.endc
.end
"""
    elif analysis == "temp":
        vgs = float(analysis_params["vgs"])
        temps = [float(t) for t in analysis_params["temps_c"]]
        if len(temps) < 2:
            raise ValueError("temp analysis requires at least two temps_c values")
        temp_list = " ".join(str(t) for t in temps)
        body = f"""* {title}
{section}
VG1 g1 0 DC {vgs}
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vdd}
{ref}
.control
echo temp_C Id > {out_txt}
foreach t {temp_list}
  set temp = $t
  op
  let id = abs(i(VS1))
  echo $t $&id >> {out_txt}
end
.endc
.end
"""
    else:
        raise ValueError(f"unsupported analysis for BSIM ref: {analysis!r}")
    path.write_text(body)


def write_acm_ngspice(
    *,
    path: Path,
    title: str,
    model: ModelSpec,
    params: str,
    osdi: Path,
    analysis: str,
    analysis_params: Mapping[str, Any],
    vdd: float,
    out_txt: Path,
) -> None:
    """Write ACM-only ngspice netlist with ``wrdata`` ASCII export."""
    if analysis == "dc":
        vg0 = float(analysis_params["vg_start"])
        vg_step = float(analysis_params["vg_step"])
        body = f"""* {title}
.model {model.spice_model} {model.module_name}
VG1 g1 0 DC 0
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vdd}
N1 d1 g1 s1 b1 {model.spice_model} {params}
.control
pre_osdi {osdi}
dc VG1 {vg0} {vdd} {vg_step}
let id = abs(i(VS1))
wrdata {out_txt} id
.endc
.end
"""
    elif analysis == "ac":
        vgs = float(analysis_params["vgs"])
        f0 = float(analysis_params["f_start"])
        f1 = float(analysis_params["f_stop"])
        nd = int(analysis_params["points_per_decade"])
        rd = _rd(analysis_params)
        body = f"""* {title}
.model {model.spice_model} {model.module_name}
VG1 g1 0 DC {vgs} AC 1
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VVDD vdd 0 DC {vdd}
RD1 vdd d1 {rd}
N1 d1 g1 s1 b1 {model.spice_model} {params}
.control
pre_osdi {osdi}
ac dec {nd} {f0} {f1}
wrdata {out_txt} vm(d1)
.endc
.end
"""
    elif analysis == "noise":
        vgs = float(analysis_params["vgs"])
        f0 = float(analysis_params["f_start"])
        f1 = float(analysis_params["f_stop"])
        nd = int(analysis_params["points_per_decade"])
        rd = _rd(analysis_params)
        body = f"""* {title}
.model {model.spice_model} {model.module_name}
VG1 g1 0 DC {vgs} AC 1
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VVDD vdd 0 DC {vdd}
RD1 vdd d1 {rd}
N1 d1 g1 s1 b1 {model.spice_model} {params}
.control
pre_osdi {osdi}
noise v(d1) VG1 dec {nd} {f0} {f1}
setplot noise1
wrdata {out_txt} onoise_spectrum
.endc
.end
"""
    elif analysis == "transient":
        v_low = float(analysis_params["v_low"])
        tr = float(analysis_params["t_rise"])
        tf = float(analysis_params["t_fall"])
        tp = float(analysis_params["t_pulse"])
        tper = float(analysis_params["t_period"])
        tstop = float(analysis_params["t_stop"])
        tstep = float(analysis_params["t_step"])
        body = f"""* {title}
.model {model.spice_model} {model.module_name}
VG1 g1 0 PULSE({v_low} {vdd} 0 {tr} {tf} {tp} {tper})
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vdd}
N1 d1 g1 s1 b1 {model.spice_model} {params}
.control
pre_osdi {osdi}
tran {tstep} {tstop}
let id = abs(i(VS1))
wrdata {out_txt} id
.endc
.end
"""
    elif analysis == "temp":
        vgs = float(analysis_params["vgs"])
        temps = [float(t) for t in analysis_params["temps_c"]]
        if len(temps) < 2:
            raise ValueError("temp analysis requires at least two temps_c values")
        temp_list = " ".join(str(t) for t in temps)
        body = f"""* {title}
.model {model.spice_model} {model.module_name}
VG1 g1 0 DC {vgs}
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vdd}
N1 d1 g1 s1 b1 {model.spice_model} {params}
.control
pre_osdi {osdi}
echo temp_C Id > {out_txt}
foreach t {temp_list}
  set temp = $t
  op
  let id = abs(i(VS1))
  echo $t $&id >> {out_txt}
end
.endc
.end
"""
    else:
        raise ValueError(f"unsupported analysis for ngspice ACM: {analysis!r}")
    path.write_text(body)


def write_acm_spectre(
    *,
    path: Path,
    title: str,
    model: ModelSpec,
    params: str,
    va_path: Path,
    analysis: str,
    analysis_params: Mapping[str, Any],
    vdd: float,
) -> None:
    """Write ACM-only Spectre netlist with ``rawfmt=nutascii``."""
    common_opts = "simulatorOptions options rawfmt=nutascii"
    if analysis == "dc":
        vg0 = float(analysis_params["vg_start"])
        vg_step = float(analysis_params["vg_step"])
        body = f"""// {title}
simulator lang=spectre
ahdl_include "{va_path}"
parameters vg={vg0} vdd={vdd}
VG1 (g1 0) vsource dc=vg type=dc
VS1 (s1 0) vsource dc=0 type=dc
VB1 (b1 0) vsource dc=0 type=dc
VD1 (d1 0) vsource dc=vdd type=dc
N1 (d1 g1 s1 b1) {model.module_name} {params}
{common_opts}
dc_sweep dc param=vg start={vg0} stop={vdd} step={vg_step}
save VS1:p
"""
    elif analysis == "ac":
        vgs = float(analysis_params["vgs"])
        f0 = float(analysis_params["f_start"])
        f1 = float(analysis_params["f_stop"])
        nd = int(analysis_params["points_per_decade"])
        rd = _rd(analysis_params)
        body = f"""// {title}
simulator lang=spectre
ahdl_include "{va_path}"
parameters vdd={vdd}
VG1 (g1 0) vsource dc={vgs} type=dc mag=1
VS1 (s1 0) vsource dc=0 type=dc
VB1 (b1 0) vsource dc=0 type=dc
VVDD (vdd 0) vsource dc=vdd type=dc
RD1 (vdd d1) resistor r={rd}
N1 (d1 g1 s1 b1) {model.module_name} {params}
{common_opts}
ac_sweep ac start={f0} stop={f1} dec={nd}
save d1
"""
    elif analysis == "noise":
        vgs = float(analysis_params["vgs"])
        f0 = float(analysis_params["f_start"])
        f1 = float(analysis_params["f_stop"])
        nd = int(analysis_params["points_per_decade"])
        rd = _rd(analysis_params)
        body = f"""// {title}
simulator lang=spectre
ahdl_include "{va_path}"
parameters vdd={vdd}
VG1 (g1 0) vsource dc={vgs} type=dc mag=1
VS1 (s1 0) vsource dc=0 type=dc
VB1 (b1 0) vsource dc=0 type=dc
VVDD (vdd 0) vsource dc=vdd type=dc
RD1 (vdd d1) resistor r={rd}
N1 (d1 g1 s1 b1) {model.module_name} {params}
{common_opts}
noise_sweep noise start={f0} stop={f1} dec={nd} oprobe=RD1 iprobe=VG1
save out
"""
    elif analysis == "transient":
        v_low = float(analysis_params["v_low"])
        tr = float(analysis_params["t_rise"])
        tf = float(analysis_params["t_fall"])
        tp = float(analysis_params["t_pulse"])
        tper = float(analysis_params["t_period"])
        tstop = float(analysis_params["t_stop"])
        tstep = float(analysis_params["t_step"])
        body = f"""// {title}
simulator lang=spectre
ahdl_include "{va_path}"
parameters vdd={vdd}
VG1 (g1 0) vsource type=pulse val0={v_low} val1=vdd delay=0 rise={tr} fall={tf} width={tp} period={tper}
VS1 (s1 0) vsource dc=0 type=dc
VB1 (b1 0) vsource dc=0 type=dc
VD1 (d1 0) vsource dc=vdd type=dc
N1 (d1 g1 s1 b1) {model.module_name} {params}
{common_opts}
tran_sweep tran stop={tstop} step={tstep}
save VS1:p
"""
    elif analysis == "temp":
        temps = [float(t) for t in analysis_params["temps_c"]]
        if len(temps) < 2:
            raise ValueError("temp analysis requires at least two temps_c values")
        vgs = float(analysis_params["vgs"])
        values = " ".join(str(t) for t in temps)
        body = f"""// {title}
simulator lang=spectre
ahdl_include "{va_path}"
parameters vdd={vdd}
VG1 (g1 0) vsource dc={vgs} type=dc
VS1 (s1 0) vsource dc=0 type=dc
VB1 (b1 0) vsource dc=0 type=dc
VD1 (d1 0) vsource dc=vdd type=dc
N1 (d1 g1 s1 b1) {model.module_name} {params}
{common_opts}
dc_temp dc values=[{values}] param=temp
save VS1:p
"""
    else:
        raise ValueError(f"unsupported analysis for spectre ACM: {analysis!r}")
    path.write_text(body)


def write_acm_hspice(
    *,
    path: Path,
    title: str,
    model: ModelSpec,
    params: str,
    analysis: str,
    analysis_params: Mapping[str, Any],
    vdd: float,
) -> None:
    """Write ACM-only HSPICE netlist with ``.print`` ASCII table.

    The VA file is supplied via the ``hspice -hdl`` CLI (case-safe path).
    Instance name uses ``X`` prefix so HSPICE treats it as a VA/subckt.
    """
    header = f"""* {title}
.option accurate gmin=1e-12
"""
    inst = f"XACM d1 g1 s1 b1 {model.module_name} {params}"
    if analysis == "dc":
        vg0 = float(analysis_params["vg_start"])
        vg_step = float(analysis_params["vg_step"])
        body = f"""{header}
VG1 g1 0 DC 0
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vdd}
{inst}
.dc VG1 {vg0} {vdd} {vg_step}
.print dc I(VD1)
.end
"""
    elif analysis == "ac":
        vgs = float(analysis_params["vgs"])
        f0 = float(analysis_params["f_start"])
        f1 = float(analysis_params["f_stop"])
        nd = int(analysis_params["points_per_decade"])
        rd = _rd(analysis_params)
        body = f"""{header}
VG1 g1 0 DC {vgs} AC 1
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VVDD vdd 0 DC {vdd}
RD1 vdd d1 {rd}
{inst}
.ac DEC {nd} {f0} {f1}
.print ac V(d1)
.end
"""
    elif analysis == "noise":
        vgs = float(analysis_params["vgs"])
        f0 = float(analysis_params["f_start"])
        f1 = float(analysis_params["f_stop"])
        nd = int(analysis_params["points_per_decade"])
        rd = _rd(analysis_params)
        body = f"""{header}
VG1 g1 0 DC {vgs} AC 1
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VVDD vdd 0 DC {vdd}
RD1 vdd d1 {rd}
{inst}
.ac DEC {nd} {f0} {f1}
.noise V(d1) VG1
.print noise onoise
.end
"""
    elif analysis == "transient":
        v_low = float(analysis_params["v_low"])
        tr = float(analysis_params["t_rise"])
        tf = float(analysis_params["t_fall"])
        tp = float(analysis_params["t_pulse"])
        tper = float(analysis_params["t_period"])
        tstop = float(analysis_params["t_stop"])
        tstep = float(analysis_params["t_step"])
        body = f"""{header}
VG1 g1 0 PULSE({v_low} {vdd} 0 {tr} {tf} {tp} {tper})
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vdd}
{inst}
.tran {tstep} {tstop}
.print tran I(VD1)
.end
"""
    elif analysis == "temp":
        vgs = float(analysis_params["vgs"])
        temps = [float(t) for t in analysis_params["temps_c"]]
        t0, t1 = temps[0], temps[-1]
        tstep = (t1 - t0) / max(len(temps) - 1, 1)
        body = f"""{header}
VG1 g1 0 DC {vgs}
VS1 s1 0 DC 0
VB1 b1 0 DC 0
VD1 d1 0 DC {vdd}
{inst}
.dc TEMP {t0} {t1} {tstep}
.print dc I(VD1)
.end
"""
    else:
        raise ValueError(f"unsupported analysis for hspice ACM: {analysis!r}")
    path.write_text(body)


__all__ = [
    "format_instance_params",
    "write_bsim_ref_ngspice",
    "write_acm_ngspice",
    "write_acm_spectre",
    "write_acm_hspice",
]
