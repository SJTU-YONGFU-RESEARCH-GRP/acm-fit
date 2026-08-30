#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_all.sh — end-to-end golden → fit → predict → eval → report
#
# Usage:
#   bash scripts/run_all.sh              # both lanes + eval (default)
#   bash scripts/run_all.sh commercial
#   bash scripts/run_all.sh ptm
#   bash scripts/run_all.sh all --skip-eval
#   bash scripts/run_all.sh all --skip-eval
#   bash scripts/run_all.sh commercial --skip-golden --iterations 25
#   bash scripts/run_all.sh --jobs 8          # parallel ngspice workers (default 4)
#   JOBS=8 bash scripts/run_all.sh
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LANE_ARG="${1:-all}"
shift || true

resolve_lanes() {
    case "$1" in
        all) echo "commercial ptm" ;;
        commercial|ptm) echo "$1" ;;
        *)
            echo "Unknown lane ${1}; expected all, commercial, or ptm." >&2
            exit 1
            ;;
    esac
}

eval_config_for_lane() {
    case "$1" in
        commercial) echo "${RELEASE_ROOT}/config/eval_suite.json" ;;
        ptm) echo "${RELEASE_ROOT}/config/eval_suite_ptm.json" ;;
        *) echo "no eval config for lane $1" >&2; exit 1 ;;
    esac
}

eval_pdks_for_lane() {
    case "$1" in
        commercial) echo "sky130_tt,gf180mcu_typical" ;;
        ptm) echo "ptm180,ptm130,ptm90,ptm65,ptm45,ptm32,ptm22" ;;
        *) echo "no eval PDKs for lane $1" >&2; exit 1 ;;
    esac
}

DO_EVAL=1
JOBS="${JOBS:-4}"
ITERATIONS=25
SKIP_GOLDEN=0
FROZEN_GOLDEN=0
SKIP_FIT=0
SKIP_PREDICT=0
FORCE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --jobs) JOBS="$2"; shift 2 ;;
        --iterations) ITERATIONS="$2"; shift 2 ;;
        --skip-golden) SKIP_GOLDEN=1; shift ;;
        --frozen-golden) FROZEN_GOLDEN=1; SKIP_GOLDEN=1; shift ;;
        --skip-fit) SKIP_FIT=1; shift ;;
        --skip-predict) SKIP_PREDICT=1; shift ;;
        --skip-eval) DO_EVAL=0; shift ;;
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

read -r -a LANES <<< "$(resolve_lanes "${LANE_ARG}")"

for LANE in "${LANES[@]}"; do
    CONFIG="${RELEASE_ROOT}/config/golden_suite_${LANE}.json"
    if [[ ! -f "${CONFIG}" ]]; then
        echo "Missing config for lane ${LANE}: ${CONFIG}" >&2
        exit 1
    fi

    echo "=== Lane: ${LANE} ==="
    if [[ "${FROZEN_GOLDEN}" -eq 1 ]]; then
        bash "${SCRIPT_DIR}/import_golden_data.sh" "${LANE}"
    fi
    python3 "${SCRIPT_DIR}/run_golden_pipeline.py" \
        --config "${CONFIG}" \
        --results-dir "${RELEASE_ROOT}/results/${LANE}" \
        --openvaf-binary "${RELEASE_ROOT}/work/openvaf-r" \
        --iterations "${ITERATIONS}" \
        --jobs "${JOBS}" \
        --simulators ngspice \
        "${GOLDEN_FLAGS[@]}"

    if [[ "${DO_EVAL}" -eq 1 ]]; then
        EVAL_CONFIG="$(eval_config_for_lane "${LANE}")"
        EVAL_PDKS="$(eval_pdks_for_lane "${LANE}")"
        echo "=== Eval (${LANE}): ACM vs BSIM (${EVAL_PDKS}) ==="
        FORCE_FLAG=()
        [[ "${FORCE}" -eq 1 ]] && FORCE_FLAG=(--force)
        python3 "${SCRIPT_DIR}/run_eval_suite.py" \
            --config "${EVAL_CONFIG}" \
            --results-dir "${RELEASE_ROOT}/results/${LANE}" \
            --models acm5 \
            --pdks "${EVAL_PDKS}" \
            --simulators ngspice \
            --jobs "${JOBS}" \
            "${FORCE_FLAG[@]}"
    fi

    echo "Done lane ${LANE}. See ${RELEASE_ROOT}/results/${LANE}/SUMMARY.md"
done

echo "All lanes complete."
