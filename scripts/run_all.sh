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
#   bash scripts/run_all.sh commercial --skip-golden --iterations 25
#   bash scripts/run_all.sh --jobs 8
#   bash scripts/run_all.sh custom       # user CSV goldens (data/golden/custom/)
#   bash scripts/run_all.sh custom --golden-from data/golden/my_run
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LANE_ARG="${1:-all}"
shift || true

GOLDEN_FROM=""
SUITE_CONFIG=""

resolve_lanes() {
    case "$1" in
        all) echo "commercial ptm" ;;
        commercial|ptm|custom) echo "$1" ;;
        *)
            echo "Unknown lane ${1}; expected all, commercial, ptm, or custom." >&2
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
        --golden-from) GOLDEN_FROM="$2"; shift 2 ;;
        --config) SUITE_CONFIG="$2"; shift 2 ;;
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
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_acm_env.sh"
bash "${SCRIPT_DIR}/setup_env.sh"

GOLDEN_FLAGS=()
[[ "${SKIP_GOLDEN}" -eq 1 ]] && GOLDEN_FLAGS+=(--skip-golden)
[[ "${SKIP_FIT}" -eq 1 ]] && GOLDEN_FLAGS+=(--skip-fit)
[[ "${SKIP_PREDICT}" -eq 1 ]] && GOLDEN_FLAGS+=(--skip-predict)

read -r -a LANES <<< "$(resolve_lanes "${LANE_ARG}")"

for LANE in "${LANES[@]}"; do
    RESULTS_LANE="${LANE}"

    if [[ "${LANE}" == "custom" ]]; then
        CONFIG="${SUITE_CONFIG:-${RELEASE_ROOT}/config/golden_suite_custom.json}"
        if [[ ! -f "${CONFIG}" ]]; then
            echo "Missing ${CONFIG}" >&2
            echo "Copy config/golden_suite_custom.example.json and edit targets." >&2
            echo "See data/BRING_YOUR_OWN.md" >&2
            exit 1
        fi
        SKIP_GOLDEN=1
        DO_EVAL=0
        GOLDEN_SRC="${GOLDEN_FROM:-${RELEASE_ROOT}/data/golden/custom}"
        GOLDEN_FLAGS=(--skip-golden)
        [[ "${SKIP_FIT}" -eq 1 ]] && GOLDEN_FLAGS+=(--skip-fit)
        [[ "${SKIP_PREDICT}" -eq 1 ]] && GOLDEN_FLAGS+=(--skip-predict)
    else
        CONFIG="${RELEASE_ROOT}/config/golden_suite_${LANE}.json"
        if [[ ! -f "${CONFIG}" ]]; then
            echo "Missing config for lane ${LANE}: ${CONFIG}" >&2
            exit 1
        fi
        GOLDEN_SRC=""
    fi

    echo "=== Lane: ${LANE} ==="
    if [[ "${LANE}" == "custom" ]]; then
        bash "${SCRIPT_DIR}/import_golden_data.sh" --from "${GOLDEN_SRC}" \
            --to "${RELEASE_ROOT}/results/${RESULTS_LANE}"
    elif [[ "${FROZEN_GOLDEN}" -eq 1 ]]; then
        bash "${SCRIPT_DIR}/import_golden_data.sh" "${LANE}"
    fi

    bash "${SCRIPT_DIR}/run_golden_pipeline.sh" \
        --config "${CONFIG}" \
        --results-dir "${RELEASE_ROOT}/results/${RESULTS_LANE}" \
        --openvaf-binary "${RELEASE_ROOT}/work/openvaf-r" \
        --iterations "${ITERATIONS}" \
        --jobs "${JOBS}" \
        --simulators ngspice \
        "${GOLDEN_FLAGS[@]}"

    if [[ "${DO_EVAL}" -eq 1 && "${LANE}" != "custom" ]]; then
        EVAL_CONFIG="$(eval_config_for_lane "${LANE}")"
        EVAL_PDKS="$(eval_pdks_for_lane "${LANE}")"
        echo "=== Eval (${LANE}): ACM vs BSIM (${EVAL_PDKS}) ==="
        FORCE_FLAG=()
        [[ "${FORCE}" -eq 1 ]] && FORCE_FLAG=(--force)
        bash "${SCRIPT_DIR}/run_eval_suite.sh" \
            --config "${EVAL_CONFIG}" \
            --results-dir "${RELEASE_ROOT}/results/${RESULTS_LANE}" \
            --models acm5 \
            --pdks "${EVAL_PDKS}" \
            --simulators ngspice \
            --jobs "${JOBS}" \
            "${FORCE_FLAG[@]}"
    fi

    echo "Done lane ${LANE}. See ${RELEASE_ROOT}/results/${RESULTS_LANE}/SUMMARY.md"
done

echo "All lanes complete."
