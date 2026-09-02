#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# run_all.sh — end-to-end golden → fit → predict → eval → report
#
# Usage:
#   bash scripts/run_all.sh              # commercial + ptm + custom (eval on PDK lanes)
#   bash scripts/run_all.sh commercial
#   bash scripts/run_all.sh ptm
#   bash scripts/run_all.sh all --skip-eval
#   bash scripts/run_all.sh commercial --skip-golden --iterations 100
#   bash scripts/run_all.sh --jobs 8
#   bash scripts/run_all.sh custom       # 8-example robustness matrix → results/custom/
#   bash scripts/run_all.sh custom --golden-from data/golden/my_run  # your BYOD data
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LANE_ARG="${1:-all}"
shift || true

GOLDEN_FROM=""
SUITE_CONFIG=""

resolve_lanes() {
    case "$1" in
        all) echo "commercial ptm custom" ;;
        commercial|ptm|custom) echo "$1" ;;
        *)
            echo "Unknown lane ${1}; expected all, commercial, ptm, or custom." >&2
            exit 1
            ;;
    esac
}

custom_golden_source() {
    if [[ -n "${GOLDEN_FROM}" ]]; then
        echo "${GOLDEN_FROM}"
        return
    fi
    local examples_root="${RELEASE_ROOT}/data/examples"
    if compgen -G "${examples_root}"/*/meta.json > /dev/null; then
        echo "${examples_root}"
        return
    fi
    local custom_root="${RELEASE_ROOT}/data/golden/custom"
    if compgen -G "${custom_root}"/*/meta.json > /dev/null; then
        echo "${custom_root}"
        return
    fi
    echo "No custom data under data/examples/ or data/golden/custom/." >&2
    echo "Run: bash scripts/build_custom_examples.sh" >&2
    exit 1
}

custom_suite_config() {
    if [[ -n "${SUITE_CONFIG}" ]]; then
        echo "${SUITE_CONFIG}"
        return
    fi
    local golden_src
    golden_src="$(custom_golden_source)"
    local user_cfg="${RELEASE_ROOT}/config/golden_suite_custom.json"
    local example_cfg="${RELEASE_ROOT}/config/golden_suite_custom.example.json"
    if [[ "${golden_src}" == *"/data/golden/custom" && -f "${user_cfg}" ]]; then
        echo "${user_cfg}"
    elif [[ -f "${example_cfg}" ]]; then
        echo "${example_cfg}"
    elif [[ -f "${user_cfg}" ]]; then
        echo "${user_cfg}"
    else
        echo "Missing ${user_cfg} (copy from golden_suite_custom.example.json)." >&2
        exit 1
    fi
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
ITERATIONS=""
SKIP_GOLDEN=0
FROZEN_GOLDEN=0
SKIP_FIT=0
SKIP_PREDICT=0
FORCE=0
SKIP_FIGURES=0
FIT_STRATEGY=""
FIT_BENCHMARK=""

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
        --skip-figures) SKIP_FIGURES=1; shift ;;
        --fit-strategy) FIT_STRATEGY="$2"; shift 2 ;;
        --fit-benchmark) FIT_BENCHMARK="$2"; shift 2 ;;
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
    LANE_DO_EVAL="${DO_EVAL}"
    LANE_GOLDEN_FLAGS=("${GOLDEN_FLAGS[@]}")

    if [[ "${LANE}" == "custom" ]]; then
        CONFIG="$(custom_suite_config)"
        GOLDEN_SRC="$(custom_golden_source)"
        LANE_DO_EVAL=0
        LANE_GOLDEN_FLAGS=(--skip-golden)
        [[ "${SKIP_FIT}" -eq 1 ]] && LANE_GOLDEN_FLAGS+=(--skip-fit)
        [[ "${SKIP_PREDICT}" -eq 1 ]] && LANE_GOLDEN_FLAGS+=(--skip-predict)
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
        echo "  custom golden: ${GOLDEN_SRC}"
        echo "  custom config: ${CONFIG}"
        bash "${SCRIPT_DIR}/import_golden_data.sh" --from "${GOLDEN_SRC}" \
            --to "${RELEASE_ROOT}/results/${RESULTS_LANE}"
    elif [[ "${FROZEN_GOLDEN}" -eq 1 ]]; then
        bash "${SCRIPT_DIR}/import_golden_data.sh" "${LANE}"
    fi

    FIT_FLAGS=()
    [[ -n "${FIT_STRATEGY}" ]] && FIT_FLAGS+=(--fit-strategy "${FIT_STRATEGY}")
    [[ -n "${FIT_BENCHMARK}" ]] && FIT_FLAGS+=(--fit-benchmark "${FIT_BENCHMARK}")

    bash "${SCRIPT_DIR}/run_golden_pipeline.sh" \
        --config "${CONFIG}" \
        --results-dir "${RELEASE_ROOT}/results/${RESULTS_LANE}" \
        --openvaf-binary "${RELEASE_ROOT}/work/openvaf-r" \
        --jobs "${JOBS}" \
        --simulators ngspice \
        ${ITERATIONS:+--iterations "${ITERATIONS}"} \
        "${FIT_FLAGS[@]}" \
        "${LANE_GOLDEN_FLAGS[@]}"

    if [[ "${LANE_DO_EVAL}" -eq 1 && "${LANE}" != "custom" ]]; then
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

if [[ "${SKIP_FIGURES}" -eq 0 ]]; then
    COMM_FIT="${RELEASE_ROOT}/results/commercial/acm5/fit"
    PTM_FIT="${RELEASE_ROOT}/results/ptm/acm5/fit"
    if [[ -d "${COMM_FIT}" && -d "${PTM_FIT}" ]] \
        && compgen -G "${COMM_FIT}"/*.json > /dev/null \
        && compgen -G "${PTM_FIT}"/*.json > /dev/null; then
        echo "=== Paper figures: commercial + ptm → figures/ ==="
        bash "${SCRIPT_DIR}/plot_paper_figures.sh"
    fi
fi

echo "All lanes complete."
