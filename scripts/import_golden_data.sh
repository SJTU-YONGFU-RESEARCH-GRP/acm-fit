#!/usr/bin/env bash
# Import frozen Id-Vg goldens into results/<lane>/golden/ (or a custom results root).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'EOF'
Usage:
  bash scripts/import_golden_data.sh <commercial|ptm> [results_root]
  bash scripts/import_golden_data.sh --from <src_dir> --to <results_root>

Copies meta.json and idvg_vds_*.csv into <results_root>/golden/.
EOF
}

SRC=""
DST=""
LANE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) SRC="$2"; shift 2 ;;
        --to) DST="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *)
            if [[ -z "${LANE}" ]]; then
                LANE="$1"
                shift
            else
                DST="$1"
                shift
            fi
            ;;
    esac
done

if [[ -n "${LANE}" && -z "${SRC}" ]]; then
    SRC="${RELEASE_ROOT}/data/golden/${LANE}"
fi

if [[ -z "${SRC}" ]]; then
    usage >&2
    exit 1
fi

if [[ -n "${LANE}" && -z "${DST}" ]]; then
    DST="${RELEASE_ROOT}/results/${LANE}"
fi

if [[ -z "${DST}" ]]; then
    echo "ERROR: missing results root (--to or second positional arg)" >&2
    usage >&2
    exit 1
fi

GOLDEN_DST="${DST}/golden"
if [[ ! -d "${SRC}" ]]; then
    echo "Missing source golden dir: ${SRC}" >&2
    exit 1
fi

mkdir -p "${GOLDEN_DST}"
rsync -a --delete \
    --include='*/' \
    --include='*.csv' \
    --include='meta.json' \
    --exclude='*' \
    "${SRC}/" "${GOLDEN_DST}/"

echo "Imported golden: ${SRC} -> ${GOLDEN_DST}"
find "${GOLDEN_DST}" -mindepth 1 -maxdepth 1 -type d | wc -l | xargs -I{} echo "  targets: {}"
