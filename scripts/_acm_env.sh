#!/usr/bin/env bash
# Shared environment for acm-fit shell drivers (PYTHONPATH + repo root).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export PYTHONPATH="${RELEASE_ROOT}/src:${PYTHONPATH:-}"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

acm_cli() {
    local module="$1"
    shift
    python3 -m "acm.cli.${module}" "$@"
}
