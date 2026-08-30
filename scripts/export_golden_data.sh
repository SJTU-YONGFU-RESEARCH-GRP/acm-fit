#!/usr/bin/env bash
# Export results/<lane>/golden/ CSV tables into data/golden/<lane>/ for redistribution.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LANE="${1:-}"
if [[ -z "${LANE}" ]]; then
    echo "Usage: bash scripts/export_golden_data.sh <commercial|ptm>" >&2
    exit 1
fi

SRC="${RELEASE_ROOT}/results/${LANE}/golden"
DST="${RELEASE_ROOT}/data/golden/${LANE}"

if [[ ! -d "${SRC}" ]]; then
    echo "Missing results golden lane: ${SRC}" >&2
    echo "Run: bash scripts/run_all.sh ${LANE} --skip-fit --skip-predict" >&2
    exit 1
fi

mkdir -p "${DST}"
rsync -a --delete \
    --include='*/' \
    --include='*.csv' \
    --include='meta.json' \
    --exclude='*' \
    "${SRC}/" "${DST}/"

echo "Exported golden ${LANE}: ${SRC} -> ${DST}"
