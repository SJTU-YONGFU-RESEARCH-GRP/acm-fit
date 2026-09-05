#!/usr/bin/env bash
# Launch one fit-benchmark worker per remaining (lane, model, target).
#
# Skips targets that are already complete or partially checkpointed (another worker
# owns them). Use after the main lane job is running, to fan out wave-3 / idle targets.
#
#   STRATEGY_JOBS=3 FIT_MODELS=acm4,acm5,qlaw_gm_j14 \
#     bash scripts/run_fit_benchmark_remaining.sh commercial ptm custom
#   bash scripts/run_fit_benchmark_remaining.sh commercial --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STRATEGY_JOBS="${STRATEGY_JOBS:-3}"
FIT_MODELS="${FIT_MODELS:-acm4,acm5,qlaw_gm_j14}"
DRY_RUN=0
LANES=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --strategy-jobs) STRATEGY_JOBS="$2"; shift 2 ;;
        --fit-models|--models) FIT_MODELS="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,10p' "$0"
            exit 0
            ;;
        *) LANES+=("$1"); shift ;;
    esac
done

if [[ ${#LANES[@]} -eq 0 ]]; then
    LANES=(commercial ptm custom)
fi

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_acm_env.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/load_pdk_env.sh"
cd "${RELEASE_ROOT}"

STRATEGIES="optuna,optuna_cmaes,optuna_gp,optuna_qmc,optuna_random,differential_evolution,dual_annealing,lbfgsb,staged,staged_optuna,staged_cmaes"

spawned=0
while IFS= read -r line; do
    lane="${line%%:*}"
    rest="${line#*:}"
    model="${rest%%:*}"
    target="${rest#*:}"
    log="${RELEASE_ROOT}/results/${lane}/fit_benchmark_${model}_${target}.log"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "would spawn lane=${lane} model=${model} target=${target} strategy_jobs=${STRATEGY_JOBS} log=${log}"
        spawned=$((spawned + 1))
        continue
    fi
    echo "spawning lane=${lane} model=${model} target=${target} strategy_jobs=${STRATEGY_JOBS} -> ${log}"
    nohup env STRATEGY_JOBS="${STRATEGY_JOBS}" FIT_MODELS="${model}" bash "${SCRIPT_DIR}/run_fit_benchmark.sh" \
        "${lane}" \
        --results-dir "${lane}" \
        --strategy-jobs "${STRATEGY_JOBS}" \
        --fit-models "${model}" \
        --targets "${target}" \
        >> "${log}" 2>&1 &
    echo "  pid=$!"
    spawned=$((spawned + 1))
done < <(
    FIT_MODELS="${FIT_MODELS}" PYTHONPATH=src python3 - "${LANES[@]}" <<'PY'
import os
import sys
from pathlib import Path

from acm.golden import load_golden_device, load_golden_config
from acm.opt.benchmark import benchmark_target_complete
from acm.opt.engine import fit_engine_from_mapping, fit_job_waves

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
N = len(STRATEGIES)
MODELS = tuple(
    s.strip() for s in os.environ.get("FIT_MODELS", "acm5").split(",") if s.strip()
)


def checkpoint_count(work_dir: Path) -> int:
    if not work_dir.is_dir():
        return 0
    return sum(
        1 for p in work_dir.iterdir() if (p / "benchmark_checkpoint.json").is_file()
    )


for lane in sys.argv[1:]:
    if lane == "custom":
        cfg_path = ROOT / "config/golden_suite_custom.example.json"
    else:
        cfg_path = ROOT / f"config/golden_suite_{lane}.json"
    if not cfg_path.is_file():
        raise SystemExit(f"missing config for lane {lane!r}: {cfg_path}")
    cfg = load_golden_config(cfg_path, ROOT)
    fit_engine = fit_engine_from_mapping(cfg.get("fit_engine"))
    golden_dir = ROOT / "results" / lane / "golden"
    target_names = tuple(sorted(cfg["_targets"]))
    waves = fit_job_waves(
        target_names,
        golden_dir=golden_dir,
        warm_start=fit_engine.warm_start,
        load_golden_device=load_golden_device,
    )
    for model in MODELS:
        bench_dir = ROOT / "results" / lane / "fit_benchmark" / model
        work_root = ROOT / "results" / lane / model / "fit" / "_work"
        in_progress = {
            name
            for name in target_names
            if 0 < checkpoint_count(work_root / name) < N
        }
        blocked: set[str] = set()
        if fit_engine.warm_start is not None:
            for wave in waves:
                active = [name for name in wave if name in in_progress]
                if not active:
                    continue
                for name in wave:
                    if benchmark_target_complete(bench_dir, name, STRATEGIES):
                        continue
                    if checkpoint_count(work_root / name) == 0:
                        blocked.add(name)
                        print(
                            f"skip {lane}:{model}:{name} reserved_for_lane_worker "
                            f"(wave with {','.join(active)})",
                            file=sys.stderr,
                        )
        for name in target_names:
            if benchmark_target_complete(bench_dir, name, STRATEGIES):
                continue
            if name in blocked:
                continue
            done = checkpoint_count(work_root / name)
            if done > 0:
                print(
                    f"skip {lane}:{model}:{name} in_progress={done}/{N}",
                    file=sys.stderr,
                )
                continue
            print(f"{lane}:{model}:{name}")
PY
)

if [[ "$spawned" -eq 0 ]]; then
    echo "no remaining targets to spawn"
else
    echo "spawned ${spawned} worker(s); existing lane jobs were left running"
fi
