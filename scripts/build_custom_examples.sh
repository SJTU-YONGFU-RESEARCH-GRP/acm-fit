#!/usr/bin/env bash
# Regenerate data/examples/custom_* robustness corpora from frozen goldens.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_acm_env.sh"
acm_cli build_examples "$@"
