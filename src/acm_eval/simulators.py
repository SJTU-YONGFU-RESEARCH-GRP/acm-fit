"""Simulator backends for the evaluation suite."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_TIME_RE = re.compile(r"^ACM_TIME\s+([0-9.eE+-]+)\s+(\d+)\s*$", re.MULTILINE)

SIMULATOR_BINARIES = {
    "ngspice": "ngspice",
    "spectre": "spectre",
    "hspice": "hspice",
}


@dataclass(frozen=True)
class SimRunResult:
    """Result of one simulator invocation."""

    runtime_s: float
    peak_rss_kb: int
    returncode: int
    log_path: Path


def require_simulator(name: str) -> str:
    """Resolve simulator binary path or fail fast.

    Args:
        name: Simulator id (`ngspice`, `spectre`, `hspice`).

    Returns:
        Absolute path to the executable.

    Raises:
        ValueError: If the simulator id is unknown.
        FileNotFoundError: If the binary is not on ``PATH``.
    """
    if name not in SIMULATOR_BINARIES:
        raise ValueError(f"unsupported simulator: {name!r}")
    binary = shutil.which(SIMULATOR_BINARIES[name])
    if binary is None:
        raise FileNotFoundError(
            f"simulator '{name}' requested but '{SIMULATOR_BINARIES[name]}' "
            f"not found on PATH"
        )
    return binary


def run_simulator(
    *,
    simulator: str,
    netlist: Path,
    cwd: Path,
    log_path: Path,
    hspice_hdl: Path | None = None,
) -> SimRunResult:
    """Run one simulator job under GNU ``/usr/bin/time``.

    Args:
        simulator: Simulator id.
        netlist: Netlist path.
        cwd: Working directory (picked up by ngspice ``.spiceinit``).
        log_path: Combined stdout/stderr log path.
        hspice_hdl: Optional lowercase VA path passed as ``hspice -hdl``.

    Returns:
        :class:`SimRunResult` with runtime and peak RSS.
    """
    time_bin = Path("/usr/bin/time")
    if not time_bin.is_file():
        raise FileNotFoundError(
            "GNU /usr/bin/time is required for peak-RSS measurement"
        )
    binary = require_simulator(simulator)
    netlist_abs = netlist.resolve()
    if simulator == "ngspice":
        cmd = [str(time_bin), "-f", "ACM_TIME %e %M", binary, "-b", str(netlist_abs)]
    elif simulator == "spectre":
        cmd = [
            str(time_bin),
            "-f",
            "ACM_TIME %e %M",
            binary,
            str(netlist_abs),
            "+log",
            str((cwd / "spectre_run.log").resolve()),
        ]
    elif simulator == "hspice":
        out_prefix = cwd / netlist.stem
        cmd = [
            str(time_bin),
            "-f",
            "ACM_TIME %e %M",
            binary,
            str(netlist_abs),
            "-o",
            str(out_prefix.resolve()),
        ]
        if hspice_hdl is not None:
            cmd.extend(["-hdl", str(hspice_hdl.resolve())])
    else:
        raise ValueError(f"unsupported simulator: {simulator!r}")

    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    log_path.write_text(combined)
    match = _TIME_RE.search(combined)
    if match is None:
        raise RuntimeError(f"failed to parse ACM_TIME for {netlist_abs}")
    return SimRunResult(
        runtime_s=float(match.group(1)),
        peak_rss_kb=int(match.group(2)),
        returncode=proc.returncode,
        log_path=log_path,
    )


__all__ = ["SimRunResult", "require_simulator", "run_simulator", "SIMULATOR_BINARIES"]
