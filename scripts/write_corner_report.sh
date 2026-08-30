#!/usr/bin/env bash
# Write CORNER_REPORT.md from fitted cards (optional standalone step).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${RELEASE_ROOT}/results/${1:-commercial}"
MODEL="${2:-acm5}"

export PYTHONPATH="${RELEASE_ROOT}/src:${PYTHONPATH:-}"
python3 - "${RESULTS_DIR}" "${MODEL}" <<'PY'
import sys
from pathlib import Path
from acm_report import write_corner_report

path = write_corner_report(
    results_dir=Path(sys.argv[1]),
    model=sys.argv[2],
)
print(path)
PY
