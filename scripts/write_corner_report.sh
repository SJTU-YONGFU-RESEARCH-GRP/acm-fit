#!/usr/bin/env bash
# Write CORNER_REPORT.md from fitted cards (optional standalone step).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${RELEASE_ROOT}/results/${1:-commercial}"
MODEL="${2:-acm5}"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_acm_env.sh"
acm_cli corner --results-dir "${RESULTS_DIR}" --model "${MODEL}"
