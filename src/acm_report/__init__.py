"""Regression report aggregation (SUMMARY.md + per-model REPORT.md)."""

from acm_report.corners import write_corner_report
from acm_report.writer import write_regression_reports

__all__ = ["write_corner_report", "write_regression_reports"]
