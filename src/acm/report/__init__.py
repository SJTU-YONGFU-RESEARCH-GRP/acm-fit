"""Regression report aggregation (SUMMARY.md + per-model REPORT.md)."""

from acm.report.corners import write_corner_report
from acm.report.plots import (
    write_bench_waveform_plots,
    write_eval_overlay_plots,
)
from acm.report.sources import discover_input_sources, report_capabilities
from acm.report.writer import write_regression_reports

__all__ = [
    "discover_input_sources",
    "report_capabilities",
    "write_corner_report",
    "write_bench_waveform_plots",
    "write_eval_overlay_plots",
    "write_regression_reports",
]
