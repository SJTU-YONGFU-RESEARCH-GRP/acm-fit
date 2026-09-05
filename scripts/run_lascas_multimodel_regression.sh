#!/usr/bin/env bash
# Launch LASCAS multi-model production fits + strategy benchmarks.
#
# Models: acm4, acm5, qlaw_gm_j14
# Resume-safe via fit cards / strategy checkpoints.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${RELEASE_ROOT}/results/logs"
mkdir -p "${LOG_DIR}"

# Production: models still missing complete PTM/commercial cards.
PROD_MODELS="${PROD_MODELS:-acm4,qlaw_gm_j14}"
# Strategy: all three paper models (completed acm5 targets are skipped).
FIT_MODELS="${FIT_MODELS:-acm4,acm5,qlaw_gm_j14}"
STRATEGY_JOBS="${STRATEGY_JOBS:-3}"
JOBS="${JOBS:-16}"
PROD_ITERATIONS="${PROD_ITERATIONS:-500}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_acm_env.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/load_pdk_env.sh"
cd "${RELEASE_ROOT}"

if [[ ! -d "${RELEASE_ROOT}/results/strategy_bench/golden" ]]; then
  mkdir -p "${RELEASE_ROOT}/results/strategy_bench"
  ln -sfn ../custom/golden "${RELEASE_ROOT}/results/strategy_bench/golden"
fi

echo "[$(date -Is)] production fits: models=${PROD_MODELS} iterations=${PROD_ITERATIONS}"
for lane in commercial ptm; do
  cfg="${RELEASE_ROOT}/config/golden_suite_${lane}.json"
  log="${LOG_DIR}/production_${lane}_multimodel.log"
  echo "  lane=${lane} -> ${log}"
  nohup env PYTHONPATH=src python3 -m acm.cli.pipeline \
    --config "${cfg}" \
    --results-dir "${RELEASE_ROOT}/results/${lane}" \
    --skip-golden \
    --skip-predict \
    --fit-models "${PROD_MODELS}" \
    --fit-strategy optuna \
    --iterations "${PROD_ITERATIONS}" \
    --jobs "${JOBS}" \
    >>"${log}" 2>&1 &
  echo "    pid=$!"
done

echo "[$(date -Is)] strategy fan-out commercial/ptm: models=${FIT_MODELS}"
nohup env STRATEGY_JOBS="${STRATEGY_JOBS}" FIT_MODELS="${FIT_MODELS}" \
  bash "${SCRIPT_DIR}/run_fit_benchmark_remaining.sh" commercial ptm \
  >>"${LOG_DIR}/strategy_remaining_spawn.log" 2>&1 &
echo "  remaining spawn pid=$!"

echo "[$(date -Is)] strategy fan-out strategy_bench (custom robustness)"
SPAWN_LOG="${LOG_DIR}/strategy_bench_spawn.log"
: >"${SPAWN_LOG}"
mapfile -t SB_JOBS < <(
  FIT_MODELS="${FIT_MODELS}" PYTHONPATH=src python3 - <<'PY'
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
TARGETS = (
    "custom_1vds_sat",
    "custom_2vds",
    "custom_3vds_std",
    "custom_sparse_vg",
)
cfg = load_golden_config(ROOT / "config/golden_suite_custom.example.json", ROOT)
known = set(cfg["_targets"])
for model in MODELS:
    bench = ROOT / "results/strategy_bench/fit_benchmark" / model
    for name in TARGETS:
        if name not in known:
            continue
        if benchmark_target_complete(bench, name, STRATEGIES):
            continue
        print(f"{model}:{name}")
PY
)

for line in "${SB_JOBS[@]:-}"; do
  [[ -z "${line}" ]] && continue
  model="${line%%:*}"
  target="${line#*:}"
  log="${LOG_DIR}/strategy_bench_${model}_${target}.log"
  echo "spawning strategy_bench model=${model} target=${target} -> ${log}" | tee -a "${SPAWN_LOG}"
  nohup env STRATEGY_JOBS="${STRATEGY_JOBS}" FIT_MODELS="${model}" \
    bash "${SCRIPT_DIR}/run_fit_benchmark.sh" custom \
      --results-dir strategy_bench \
      --strategy-jobs "${STRATEGY_JOBS}" \
      --fit-models "${model}" \
      --targets "${target}" \
      >>"${log}" 2>&1 &
  echo "  pid=$!" | tee -a "${SPAWN_LOG}"
done

echo "[$(date -Is)] launched. Monitor:"
echo "  pgrep -af 'acm.cli.pipeline|run_fit_benchmark'"
echo "  tail -f ${LOG_DIR}/production_*.log"
echo "  bash /home/yongfu/proj/spice_modeling/.cursor/skills/st/scripts/status.sh --results-dir ${RELEASE_ROOT}/results"
