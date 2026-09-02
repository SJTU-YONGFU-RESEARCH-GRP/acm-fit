#!/usr/bin/env bash
# Compare DC fit strategies (writes results/<results-dir>/FIT_BENCHMARK.md).
#
# Parallelism: in benchmark mode the pipeline runs one target at a time; use
# run_fit_benchmark_remaining.sh to fan out idle targets without stopping lane jobs.
# Publication default: 500 trials, strategy_jobs=1 (avoids Optuna/SciPy thread deadlocks).
# Quick smoke:  bash scripts/run_fit_benchmark.sh custom --iterations 25 --jobs 8
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LANE="${1:-custom}"
shift || true

STRATEGIES="optuna,optuna_cmaes,optuna_gp,optuna_qmc,optuna_random,differential_evolution,dual_annealing,lbfgsb,staged,staged_optuna,staged_cmaes"
ITERATIONS="500"
JOBS="${JOBS:-48}"
STRATEGY_JOBS="${STRATEGY_JOBS:-1}"
RESULTS_SUBDIR=""
EXTRA=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --strategies) STRATEGIES="$2"; shift 2 ;;
        --iterations) ITERATIONS="$2"; shift 2 ;;
        --jobs) JOBS="$2"; shift 2 ;;
        --strategy-jobs) STRATEGY_JOBS="$2"; shift 2 ;;
        --results-dir) RESULTS_SUBDIR="$2"; shift 2 ;;
        --targets) EXTRA+=("$1" "$2"); shift 2 ;;
        *) EXTRA+=("$1"); shift ;;
    esac
done

CONFIG="${RELEASE_ROOT}/config/golden_suite_${LANE}.json"
if [[ "${LANE}" == "custom" ]]; then
    CONFIG="${RELEASE_ROOT}/config/golden_suite_custom.example.json"
fi
if [[ ! -f "${CONFIG}" ]]; then
    echo "Missing config for lane ${LANE}: ${CONFIG}" >&2
    exit 1
fi

if [[ -z "${RESULTS_SUBDIR}" ]]; then
    RESULTS_SUBDIR="${LANE}"
fi
RESULTS_DIR="${RELEASE_ROOT}/results/${RESULTS_SUBDIR}"

if [[ ! -d "${RESULTS_DIR}/golden" ]]; then
    if [[ "${LANE}" == "custom" && -d "${RELEASE_ROOT}/results/custom/golden" ]]; then
        ln -sfn "../custom/golden" "${RESULTS_DIR}/golden"
    else
        echo "Missing golden corpus: ${RESULTS_DIR}/golden" >&2
        echo "Run the lane once with --frozen-golden or import goldens first." >&2
        exit 1
    fi
fi

STRATEGY_FLAG=(--strategy-jobs "${STRATEGY_JOBS}")

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_acm_env.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/load_pdk_env.sh"

echo "Strategy benchmark: lane=${LANE} results=${RESULTS_DIR} iterations=${ITERATIONS} jobs=${JOBS} ${STRATEGY_JOBS:+strategy_jobs=${STRATEGY_JOBS}}"
cd "${RELEASE_ROOT}"
PYTHONPATH=src python3 -m acm.cli.pipeline \
    --config "${CONFIG}" \
    --results-dir "${RESULTS_DIR}" \
    --skip-golden \
    --skip-predict \
    --fit-benchmark "${STRATEGIES}" \
    --iterations "${ITERATIONS}" \
    --jobs "${JOBS}" \
    "${STRATEGY_FLAG[@]}" \
    "${EXTRA[@]}"

echo "Strategy benchmark complete: ${RESULTS_DIR}/FIT_BENCHMARK.md"
