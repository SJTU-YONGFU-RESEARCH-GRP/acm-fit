#!/usr/bin/env bash
# Remove generated artifacts (results lanes, work cache). Keeps config, models, figures.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LANE=""
ALL=0

usage() {
    cat <<'EOF'
Usage:
  bash scripts/clean.sh              # remove work/ + all results/<lane>/
  bash scripts/clean.sh smoke        # remove only results/smoke/
  bash scripts/clean.sh commercial   # remove only results/commercial/
  bash scripts/clean.sh --pycache    # also remove __pycache__ / *.pyc under src/

Does not delete: config/pdk_env.local.json, vendor/, models/, figures/, .venv/
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --pycache) ALL=1; shift ;;
        smoke|commercial|ptm)
            if [[ -n "${LANE}" ]]; then
                echo "Specify at most one lane, or none for all lanes." >&2
                exit 1
            fi
            LANE="$1"
            shift
            ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

rm -rf "${RELEASE_ROOT}/work"

if [[ -n "${LANE}" ]]; then
    rm -rf "${RELEASE_ROOT}/results/${LANE}"
    echo "Removed results/${LANE}/ and work/"
else
    find "${RELEASE_ROOT}/results" -mindepth 1 -maxdepth 1 ! -name '.gitkeep' -exec rm -rf {} +
    echo "Removed all results/<lane>/ and work/"
fi

if [[ "${ALL}" -eq 1 ]]; then
    find "${RELEASE_ROOT}/src" -type d -name __pycache__ -prune -exec rm -rf {} +
    find "${RELEASE_ROOT}/src" -name '*.pyc' -delete
    echo "Removed Python cache under src/"
fi
