#!/usr/bin/env bash
# Fast CI / release validation: full custom robustness matrix (8 targets),
# reduced fit iterations, no predict benches. Output: results/custom/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${SCRIPT_DIR}/run_all.sh" custom \
    --iterations 5 \
    --skip-predict \
    --jobs 2 \
    --fit-strategy optuna

echo "Smoke OK — see $(cd "${SCRIPT_DIR}/.." && pwd)/results/custom/SUMMARY.md"
echo "Note: production default is Optuna with relative Id loss (see fit_loss/fit_engine in config/golden_suite_*.json)."
