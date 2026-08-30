#!/usr/bin/env bash
# Sync Python sources from the monorepo src/ tree into this release package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MONOREPO_SRC="$(cd "${RELEASE_ROOT}/../../../src" && pwd)"

rsync -a --delete \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "${MONOREPO_SRC}/" "${RELEASE_ROOT}/src/"

echo "Synced ${MONOREPO_SRC} -> ${RELEASE_ROOT}/src"
