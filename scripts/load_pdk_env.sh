#!/usr/bin/env bash
# Load PDK path environment from config/pdk_env.local.json (copy from pdk_env.example.json).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${RELEASE_ROOT}/config/pdk_env.local.json"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: missing ${ENV_FILE}" >&2
    echo "Copy config/pdk_env.example.json to config/pdk_env.local.json and set paths." >&2
    exit 1
fi

eval "$(
python3 - "${ENV_FILE}" <<'PY'
import json, shlex, sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
env = payload.get("env") or {}
for key, value in env.items():
    print(f"export {key}={shlex.quote(str(value))}")
PY
)"

echo "PDK env loaded from ${ENV_FILE}"
