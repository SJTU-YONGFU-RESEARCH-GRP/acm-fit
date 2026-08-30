#!/usr/bin/env bash
# Fast CI / release validation: single PTM node, minimal fit iterations.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/load_pdk_env.sh"
bash "${SCRIPT_DIR}/setup_env.sh"

export PYTHONPATH="${RELEASE_ROOT}/src:${PYTHONPATH:-}"

python3 "${SCRIPT_DIR}/run_golden_pipeline.py" \
    --config "${RELEASE_ROOT}/config/golden_suite_smoke.json" \
    --results-dir "${RELEASE_ROOT}/results/smoke" \
    --openvaf-binary "${RELEASE_ROOT}/work/openvaf-r" \
    --iterations 5 \
    --jobs 1 \
    --simulators ngspice

echo "Smoke OK — see ${RELEASE_ROOT}/results/smoke/SUMMARY.md"
