#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_all.sh — end-to-end golden → fit → predict → report
#
# Usage:
#   bash scripts/run_all.sh commercial
#   bash scripts/run_all.sh ptm
#   bash scripts/run_all.sh commercial --skip-golden --iterations 25
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LANE="${1:-commercial}"
shift || true

CONFIG="${RELEASE_ROOT}/config/golden_suite_${LANE}.json"
if [[ ! -f "${CONFIG}" ]]; then
    echo "Unknown lane ${LANE}; expected commercial or ptm." >&2
    exit 1
fi

JOBS="${JOBS:-4}"
ITERATIONS=25
SKIP_GOLDEN=0
SKIP_FIT=0
SKIP_PREDICT=0
DO_EVAL=0
FORCE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --jobs) JOBS="$2"; shift 2 ;;
        --iterations) ITERATIONS="$2"; shift 2 ;;
        --skip-golden) SKIP_GOLDEN=1; shift ;;
        --skip-fit) SKIP_FIT=1; shift ;;
        --skip-predict) SKIP_PREDICT=1; shift ;;
        --eval) DO_EVAL=1; shift ;;
        --force) FORCE=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/load_pdk_env.sh"
bash "${SCRIPT_DIR}/setup_env.sh"

GOLDEN_FLAGS=()
[[ "${SKIP_GOLDEN}" -eq 1 ]] && GOLDEN_FLAGS+=(--skip-golden)
[[ "${SKIP_FIT}" -eq 1 ]] && GOLDEN_FLAGS+=(--skip-fit)
[[ "${SKIP_PREDICT}" -eq 1 ]] && GOLDEN_FLAGS+=(--skip-predict)

export PYTHONPATH="${RELEASE_ROOT}/src:${PYTHONPATH:-}"

echo "=== Lane: ${LANE} ==="
python3 "${SCRIPT_DIR}/run_golden_pipeline.py" \
    --config "${CONFIG}" \
    --results-dir "${RELEASE_ROOT}/results/${LANE}" \
    --openvaf-binary "${RELEASE_ROOT}/work/openvaf-r" \
    --iterations "${ITERATIONS}" \
    --jobs "${JOBS}" \
    --simulators ngspice \
    "${GOLDEN_FLAGS[@]}"

if [[ "${DO_EVAL}" -eq 1 ]]; then
    FORCE_FLAG=()
    [[ "${FORCE}" -eq 1 ]] && FORCE_FLAG=(--force)
    python3 "${SCRIPT_DIR}/run_eval_suite.py" \
        --config "${RELEASE_ROOT}/config/eval_suite.json" \
        --results-dir "${RELEASE_ROOT}/results/${LANE}" \
        --models acm5 \
        --pdks sky130_tt,gf180mcu_typical \
        --simulators ngspice \
        --jobs "${JOBS}" \
        "${FORCE_FLAG[@]}"
fi

echo "Done. See ${RELEASE_ROOT}/results/${LANE}/SUMMARY.md"
