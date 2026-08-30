"""Export simulator raw outputs into common ``acm.csv`` / ``ref.csv`` waveforms."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .waveforms import (
    parse_hspice_print_table,
    parse_nutascii,
    parse_nutascii_onoise,
    wrdata_to_xy,
    write_xy_csv,
)


def export_ngspice_waveform(
    *,
    analysis: str,
    raw_path: Path,
    csv_path: Path,
) -> None:
    """Convert ngspice ``wrdata``/temp table into 2-col CSV."""
    if analysis == "temp":
        raw = np.loadtxt(raw_path, skiprows=1)
        if raw.ndim != 2 or raw.shape[1] < 2:
            raise ValueError(f"bad temp table {raw_path}: {raw.shape}")
        x, y = raw[:, 0], np.abs(raw[:, 1])
    else:
        x, y = wrdata_to_xy(raw_path)
        if analysis in {"dc", "transient"}:
            y = np.abs(y)
    write_xy_csv(csv_path, x, y)


def export_spectre_waveform(
    *,
    analysis: str,
    job_dir: Path,
    netlist_stem: str,
    csv_path: Path,
) -> None:
    """Convert Spectre nutascii ``.raw`` into 2-col CSV."""
    raw_path = job_dir / f"{netlist_stem}.raw"
    if not raw_path.is_file():
        candidates = sorted(job_dir.glob("*.raw"))
        if not candidates:
            raise FileNotFoundError(f"missing Spectre nutascii .raw in {job_dir}")
        raw_path = candidates[0]
    if analysis == "noise":
        x, y = parse_nutascii_onoise(raw_path)
    else:
        magnitude = analysis == "ac"
        x, y = parse_nutascii(raw_path, magnitude=magnitude)
        if analysis in {"dc", "transient", "temp"}:
            y = np.abs(y)
    write_xy_csv(csv_path, x, y)


def export_hspice_waveform(
    *,
    analysis: str,
    lis_path: Path,
    csv_path: Path,
) -> None:
    """Convert HSPICE ``.lis`` print table into 2-col CSV."""
    x, y = parse_hspice_print_table(lis_path, y_column=1)
    if analysis == "ac":
        y = np.abs(y)
    elif analysis in {"dc", "transient", "temp"}:
        y = np.abs(y)
    write_xy_csv(csv_path, x, y)


def assert_hspice_va_loaded(lis_path: Path) -> None:
    """Fail if HSPICE did not instantiate any Verilog-A device."""
    text = lis_path.read_text(errors="ignore")
    match = re.search(r"# va device\s*=\s*(\d+)", text)
    if match is None:
        raise RuntimeError(f"HSPICE listing missing VA device count: {lis_path}")
    if int(match.group(1)) < 1:
        raise RuntimeError(
            f"HSPICE loaded 0 VA devices (need hspice -hdl with lowercase VA path); "
            f"see {lis_path}"
        )


__all__ = [
    "export_ngspice_waveform",
    "export_spectre_waveform",
    "export_hspice_waveform",
    "assert_hspice_va_loaded",
]
