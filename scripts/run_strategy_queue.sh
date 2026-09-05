#!/usr/bin/env bash
# Resume incomplete strategy-bench targets with higher strategy parallelism.
# Keeps at most MAX_WORKERS concurrent target processes.
#
#   STRATEGY_JOBS=8 JOBS=8 MAX_WORKERS=6 bash scripts/run_strategy_queue.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${RELEASE_ROOT}/results/logs"
mkdir -p "${LOG_DIR}"

FIT_MODELS="${FIT_MODELS:-acm4,qlaw_gm_j14}"
STRATEGY_JOBS="${STRATEGY_JOBS:-8}"
JOBS="${JOBS:-8}"
MAX_WORKERS="${MAX_WORKERS:-6}"
POLL_SEC="${POLL_SEC:-30}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_acm_env.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/load_pdk_env.sh"
cd "${RELEASE_ROOT}"

QUEUE_FILE="${LOG_DIR}/strategy_queue_jobs.txt"
FIT_MODELS="${FIT_MODELS}" PYTHONPATH=src python3 - <<'PY' >"${QUEUE_FILE}"
import os
from pathlib import Path
from acm.golden import load_golden_config
from acm.opt.benchmark import benchmark_target_complete

ROOT = Path(".")
STRATEGIES = tuple(
    s.strip()
    for s in (
        "optuna,optuna_cmaes,optuna_gp,optuna_qmc,optuna_random,"
        "differential_evolution,dual_annealing,lbfgsb,staged,"
        "staged_optuna,staged_cmaes"
    ).split(",")
    if s.strip()
)
MODELS = tuple(s.strip() for s in os.environ["FIT_MODELS"].split(",") if s.strip())

def emit(lane, cfg_name, results_subdir, targets=None):
    cfg = load_golden_config(ROOT / cfg_name, ROOT)
    names = targets if targets is not None else sorted(cfg["_targets"])
    known = set(cfg["_targets"])
    for model in MODELS:
        bench = ROOT / "results" / results_subdir / "fit_benchmark" / model
        for name in names:
            if name not in known:
                continue
            if benchmark_target_complete(bench, name, STRATEGIES):
                continue
            # lane|results_subdir|model|target
            print(f"{lane}|{results_subdir}|{model}|{name}")

emit("commercial", "config/golden_suite_commercial.json", "commercial")
emit("ptm", "config/golden_suite_ptm.json", "ptm")
emit(
    "custom",
    "config/golden_suite_custom.example.json",
    "strategy_bench",
    ["custom_1vds_sat", "custom_2vds", "custom_3vds_std", "custom_sparse_vg"],
)
PY

mapfile -t JOBS_LIST < "${QUEUE_FILE}"
echo "[$(date -Is)] queue ${#JOBS_LIST[@]} remaining jobs; STRATEGY_JOBS=${STRATEGY_JOBS} JOBS=${JOBS} MAX_WORKERS=${MAX_WORKERS}"

declare -A PID_TO_JOB=()

running_count() {
  local n=0 pid
  for pid in "${!PID_TO_JOB[@]}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      n=$((n + 1))
    else
      echo "[$(date -Is)] finished ${PID_TO_JOB[$pid]} (pid=${pid})"
      unset "PID_TO_JOB[${pid}]"
    fi
  done
  echo "${n}"
}

spawn_one() {
  local spec="$1"
  local lane results_subdir model target log pid
  IFS='|' read -r lane results_subdir model target <<<"${spec}"
  log="${LOG_DIR}/strategy_q_${model}_${target}.log"
  echo "[$(date -Is)] spawn ${lane}/${model}/${target} strategy_jobs=${STRATEGY_JOBS} jobs=${JOBS} -> ${log}"
  nohup env STRATEGY_JOBS="${STRATEGY_JOBS}" JOBS="${JOBS}" FIT_MODELS="${model}" \
    bash "${SCRIPT_DIR}/run_fit_benchmark.sh" "${lane}" \
      --results-dir "${results_subdir}" \
      --strategy-jobs "${STRATEGY_JOBS}" \
      --jobs "${JOBS}" \
      --fit-models "${model}" \
      --targets "${target}" \
      >>"${log}" 2>&1 &
  pid=$!
  PID_TO_JOB["${pid}"]="${lane}/${model}/${target}"
  echo "  pid=${pid}"
}

idx=0
total=${#JOBS_LIST[@]}
while (( idx < total )) || (( ${#PID_TO_JOB[@]} > 0 )); do
  # reap
  alive=0
  for pid in "${!PID_TO_JOB[@]}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      alive=$((alive + 1))
    else
      echo "[$(date -Is)] finished ${PID_TO_JOB[$pid]} (pid=${pid})"
      unset "PID_TO_JOB[${pid}]"
    fi
  done

  while (( alive < MAX_WORKERS && idx < total )); do
    spawn_one "${JOBS_LIST[$idx]}"
    idx=$((idx + 1))
    alive=$((alive + 1))
  done

  if (( idx >= total && alive == 0 )); then
    break
  fi
  sleep "${POLL_SEC}"
done

echo "[$(date -Is)] strategy queue drained"
