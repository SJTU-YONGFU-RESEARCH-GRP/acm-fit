#!/usr/bin/env bash
# Copy frozen BSIM I-V goldens from data/golden/<lane>/ into results/<lane>/golden/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LANE="${1:-}"
RESULTS_ROOT="${2:-}"
if [[ -z "${LANE}" ]]; then
    echo "Usage: bash scripts/import_golden_data.sh <commercial|ptm> [results_root]" >&2
    exit 1
fi

SRC="${RELEASE_ROOT}/data/golden/${LANE}"
if [[ -n "${RESULTS_ROOT}" ]]; then
    DST="${RESULTS_ROOT}/golden"
else
    DST="${RELEASE_ROOT}/results/${LANE}/golden"
fi

if [[ ! -d "${SRC}" ]]; then
    echo "Missing frozen golden lane: ${SRC}" >&2
    exit 1
fi

mkdir -p "${DST}"
rsync -a --delete \
    --include='*/' \
    --include='*.csv' \
    --include='meta.json' \
    --exclude='*' \
    "${SRC}/" "${DST}/"

echo "Imported frozen golden ${LANE}: ${SRC} -> ${DST}"
find "${DST}" -mindepth 1 -maxdepth 1 -type d | wc -l | xargs -I{} echo "  targets: {}"
