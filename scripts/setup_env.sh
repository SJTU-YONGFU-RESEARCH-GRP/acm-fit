#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# setup_env.sh — verify ngspice and compile ACM-5 OSDI with OpenVAF-Reloaded
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORK_DIR="${RELEASE_ROOT}/work"
ACM5_VA_DIR="${RELEASE_ROOT}/models/acm5"

mkdir -p "${WORK_DIR}"

if ! command -v ngspice &>/dev/null; then
    echo "ERROR: ngspice not found in PATH" >&2
    exit 1
fi
ngspice --version 2>&1 | head -1

_nmos_osdi="${ACM5_VA_DIR}/NMOS_ACM_2V0.osdi"
_pmos_osdi="${ACM5_VA_DIR}/PMOS_ACM_2V0.osdi"
if [[ -f "${_nmos_osdi}" && -f "${_pmos_osdi}" ]]; then
    echo "Pre-built OSDI present in models/acm5/"
    ls -lh "${ACM5_VA_DIR}"/*.osdi
    echo "Setup complete."
    exit 0
fi

OPENVAF_BIN=""
if command -v openvaf-r &>/dev/null; then
    OPENVAF_BIN="openvaf-r"
elif [[ -x "${WORK_DIR}/openvaf-r" ]]; then
    OPENVAF_BIN="${WORK_DIR}/openvaf-r"
fi

if [[ -z "${OPENVAF_BIN}" ]]; then
    OPENVAF_VERSION="20260616-2-gc592eed6"
    OPENVAF_ARCHIVE="openvaf-reloaded-${OPENVAF_VERSION}-linux_x64.tar.gz"
    OPENVAF_MIRRORS=(
        "http://spiceopus.si/openvaf/download/${OPENVAF_ARCHIVE}"
        "https://fides.fe.uni-lj.si/openvaf/download/${OPENVAF_ARCHIVE}"
    )
    for url in "${OPENVAF_MIRRORS[@]}"; do
        echo "Trying ${url} ..."
        if wget --timeout=30 --tries=1 -O "${WORK_DIR}/${OPENVAF_ARCHIVE}" "${url}"; then
            tar -xzf "${WORK_DIR}/${OPENVAF_ARCHIVE}" -C "${WORK_DIR}/"
            rm -f "${WORK_DIR}/${OPENVAF_ARCHIVE}"
            chmod +x "${WORK_DIR}/openvaf-r"
            OPENVAF_BIN="${WORK_DIR}/openvaf-r"
            break
        fi
        rm -f "${WORK_DIR}/${OPENVAF_ARCHIVE}"
    done
fi

if [[ -n "${OPENVAF_BIN}" ]]; then
    echo "OpenVAF-Reloaded: ${OPENVAF_BIN}"
    for va in "${ACM5_VA_DIR}/NMOS_ACM_2V0.va" "${ACM5_VA_DIR}/PMOS_ACM_2V0.va"; do
        if ! "${OPENVAF_BIN}" "${va}"; then
            echo "WARNING: OpenVAF compile failed for ${va}; ensure pre-built .osdi is present." >&2
        fi
    done
else
    echo "OpenVAF not available; ship pre-built .osdi under models/acm5/." >&2
    exit 1
fi

ls -lh "${ACM5_VA_DIR}"/*.osdi 2>/dev/null || true
echo "Setup complete."
