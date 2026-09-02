#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_acm_env.sh"

ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${ROOT}/figures"
LASCAS_FIG_DIR="${ROOT}/../../writing/lascas/figures"

acm_cli figures --strategy-bench-only --out-dir "${OUT_DIR}" "$@"

if [[ -d "${LASCAS_FIG_DIR}" ]]; then
  for name in fig_strategy_heatmap fig_strategy_runtime; do
    if [[ -f "${OUT_DIR}/${name}.png" ]]; then
      cp -f "${OUT_DIR}/${name}.png" "${LASCAS_FIG_DIR}/${name}.png"
      echo "copied ${name}.png -> ${LASCAS_FIG_DIR}/"
    fi
  done
  LASCAS_ROOT="$(cd "${LASCAS_FIG_DIR}/.." && pwd)"
  if [[ -f "${LASCAS_ROOT}/export_figures_pdf.py" ]]; then
    (cd "${LASCAS_ROOT}" && python3 export_figures_pdf.py)
  fi
fi
