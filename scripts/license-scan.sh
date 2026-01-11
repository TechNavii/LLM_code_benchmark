#!/usr/bin/env bash
set -euo pipefail

# license-scan.sh - Run license compliance scanning for the benchmark repository
# This script scans Python dependencies for license compliance and ensures
# only allowlisted licenses are used.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
POLICY_FILE="${REPO_ROOT}/.license-policy.txt"
INVENTORY_FILE="${REPO_ROOT}/docs/license-inventory.txt"

cd "${REPO_ROOT}"

# Check Python version meets requirements
source "${SCRIPT_DIR}/check-python-version.sh"
check_python_version python3

# Ensure virtualenv exists
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtualenv at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
fi

# Ensure pip-licenses is installed
echo "Ensuring pip-licenses is installed..."
"${VENV_DIR}/bin/pip" install -q pip-licenses

# Define allowed licenses (standard permissive OSS licenses)
# These licenses are generally compatible with commercial and open-source use
ALLOWED_LICENSES=(
    "MIT"
    "MIT License"
    "MIT-0"
    "BSD"
    "BSD License"
    "BSD-2-Clause"
    "BSD-3-Clause"
    "BSD 3-Clause"
    "Apache"
    "Apache License"
    "Apache-2.0"
    "Apache 2.0"
    "Apache License 2.0"
    "Apache Software License"
    "ISC"
    "ISC License"
    "Python Software Foundation License"
    "PSF"
    "PSF-2.0"
    "Unlicense"
    "WTFPL"
    "CC0"
    "CC0 1.0 Universal"
    "Public Domain"
    "Mozilla Public License 2.0"
    "MPL-2.0"
    "LGPL"
    "LGPLv2"
    "LGPLv3"
    "LGPL-2.1"
    "LGPL-3.0"
    "GNU Lesser General Public License v2"
    "GNU Lesser General Public License v3"
    "GNU Lesser General Public License v2 or later (LGPLv2+)"
    "GNU Lesser General Public License v3 or later (LGPLv3+)"
    "Zlib"
    "zlib/libpng"
)

# Define denied licenses (copyleft licenses that may require source disclosure)
# These require careful review before use
DENIED_LICENSES=(
    "GPL"
    "GPL-2.0"
    "GPL-3.0"
    "GNU General Public License"
    "GNU General Public License v2"
    "GNU General Public License v3"
    "AGPL"
    "AGPL-3.0"
    "GNU Affero General Public License"
)

echo "Running license compliance scan..."

# Generate license inventory (offline scan of installed packages)
echo "Generating license inventory..."
mkdir -p "$(dirname "${INVENTORY_FILE}")"

# Note: We scan the currently installed packages in the virtualenv
# The virtualenv is already populated by other scripts (lint.sh, test.sh, etc.)
# This avoids conflicting version issues when combining requirements files
# and ensures we're scanning what's actually installed

# Generate the inventory
"${VENV_DIR}/bin/pip-licenses" \
    --format=markdown \
    --with-urls \
    --with-authors \
    --order=license \
    > "${INVENTORY_FILE}"

echo "License inventory saved to ${INVENTORY_FILE}"

# Get licenses in CSV format for validation
LICENSE_CSV=$("${VENV_DIR}/bin/pip-licenses" --format=csv)

# Track violations
VIOLATIONS=""
UNKNOWN_LICENSES=""
HAS_VIOLATIONS=false
HAS_UNKNOWN=false

# Check each package license
while IFS=',' read -r name version license; do
    # Skip header row
    if [[ "$name" == "\"Name\"" || "$name" == "Name" ]]; then
        continue
    fi

    # Remove quotes from all fields
    name="${name//\"/}"
    version="${version//\"/}"
    license="${license//\"/}"

    # Skip empty or UNKNOWN
    if [[ -z "$license" || "$license" == "UNKNOWN" ]]; then
        UNKNOWN_LICENSES="${UNKNOWN_LICENSES}  - ${name} (${version}): ${license}\n"
        HAS_UNKNOWN=true
        continue
    fi

    # Check if license is allowed first (LGPL is allowed but contains "GPL")
    is_allowed=false
    for allowed in "${ALLOWED_LICENSES[@]}"; do
        if [[ "$license" == *"$allowed"* ]]; then
            is_allowed=true
            break
        fi
    done

    if [[ "$is_allowed" == true ]]; then
        continue
    fi

    # Check if license is denied (only if not already allowed)
    is_denied=false
    for denied in "${DENIED_LICENSES[@]}"; do
        if [[ "$license" == *"$denied"* ]]; then
            VIOLATIONS="${VIOLATIONS}  - ${name} (${version}): ${license} [DENIED]\n"
            HAS_VIOLATIONS=true
            is_denied=true
            break
        fi
    done

    if [[ "$is_denied" == true ]]; then
        continue
    fi

    # License is neither allowed nor denied - needs review
    UNKNOWN_LICENSES="${UNKNOWN_LICENSES}  - ${name} (${version}): ${license} [NEEDS REVIEW]\n"
    HAS_UNKNOWN=true
done <<< "${LICENSE_CSV}"

# Load package-specific allowlist from policy file if it exists
ALLOWLISTED_PACKAGES=""
if [ -f "${POLICY_FILE}" ]; then
    echo "Loading license policy from ${POLICY_FILE}"
    while IFS= read -r line; do
        # Skip empty lines and comments
        if [[ -z "$line" || "$line" =~ ^# ]]; then
            continue
        fi
        # Add to allowlisted packages
        ALLOWLISTED_PACKAGES="${ALLOWLISTED_PACKAGES}|${line}"
    done < "${POLICY_FILE}"
fi

# Report results
echo ""
echo "=== License Compliance Report ==="
echo ""

if [[ "$HAS_VIOLATIONS" == true ]]; then
    echo "DENIED LICENSES FOUND:"
    echo -e "${VIOLATIONS}"

    # Check if any violations are allowlisted
    ACTUAL_VIOLATIONS=false
    while IFS= read -r line; do
        if [[ -n "$line" ]]; then
            pkg_name=$(echo "$line" | sed -n 's/.*- \([^ ]*\) .*/\1/p')
            if [[ -n "$pkg_name" && ! "$ALLOWLISTED_PACKAGES" == *"|${pkg_name}|"* && ! "$ALLOWLISTED_PACKAGES" == *"|${pkg_name}" ]]; then
                ACTUAL_VIOLATIONS=true
            fi
        fi
    done <<< "$(echo -e "${VIOLATIONS}")"

    if [[ "$ACTUAL_VIOLATIONS" == true ]]; then
        echo "ERROR: Denied licenses found. Add packages to .license-policy.txt with justification if acceptable."
        exit 1
    else
        echo "NOTE: All violations are allowlisted in .license-policy.txt"
    fi
fi

if [[ "$HAS_UNKNOWN" == true ]]; then
    echo "LICENSES REQUIRING REVIEW:"
    echo -e "${UNKNOWN_LICENSES}"
    echo ""
    echo "WARNING: Unknown or unreviewed licenses found."
    echo "Add to allowed/denied lists or create exceptions in .license-policy.txt with justification."
    # Warn-only initially for brownfield adoption
    # exit 1
fi

if [[ "$HAS_VIOLATIONS" == false && "$HAS_UNKNOWN" == false ]]; then
    echo "All licenses are approved."
fi

echo ""
echo "Full inventory: ${INVENTORY_FILE}"
echo ""
echo "✓ License compliance scan completed"
