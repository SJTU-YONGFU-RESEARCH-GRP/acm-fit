"""Regression report aggregation (SUMMARY.md + per-model REPORT.md)."""

from acm_report.corners import write_corner_report
from acm_report.plots import write_eval_overlay_plots
from acm_report.sources import discover_input_sources, report_capabilities
from acm_report.writer import write_regression_reports

__all__ = [
    "discover_input_sources",
    "report_capabilities",
    "write_corner_report",
    "write_eval_overlay_plots",
    "write_regression_reports",
]
