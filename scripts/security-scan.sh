#!/usr/bin/env bash
set -euo pipefail

# security-scan.sh - Run dependency vulnerability scanning for the benchmark repository
# This script scans Python dependencies for known security vulnerabilities

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

cd "${REPO_ROOT}"

# Ensure virtualenv exists
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtualenv at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
fi

# Install dependencies if needed
echo "Ensuring dependencies are installed..."
"${VENV_DIR}/bin/pip" install -q --upgrade pip
"${VENV_DIR}/bin/pip" install -q pip-audit

# Run pip-audit on all requirements files
echo "Running pip-audit on dependencies..."

# Create a combined requirements file for scanning
TEMP_REQ=$(mktemp)
trap "rm -f ${TEMP_REQ}" EXIT

cat server/requirements.txt harness/requirements.txt requirements-dev.txt > "${TEMP_REQ}"

# Run pip-audit with suppression support
# Start with warn-only mode by using --ignore-vuln for known acceptable issues
# Uncomment the --require-hashes flag for stricter checks when lockfiles are added

SUPPRESSIONS_FILE="${REPO_ROOT}/.pip-audit-suppressions.txt"

if [ -f "${SUPPRESSIONS_FILE}" ]; then
    echo "Using suppressions from ${SUPPRESSIONS_FILE}"
    IGNORE_ARGS=""
    while IFS= read -r vuln_id; do
        # Skip empty lines and comments
        if [[ -z "$vuln_id" || "$vuln_id" =~ ^# ]]; then
            continue
        fi
        IGNORE_ARGS="${IGNORE_ARGS} --ignore-vuln ${vuln_id}"
    done < "${SUPPRESSIONS_FILE}"

    "${VENV_DIR}/bin/pip-audit" -r "${TEMP_REQ}" ${IGNORE_ARGS} || {
        echo "⚠️  Security scan found vulnerabilities (see above)"
        echo "To suppress known/acceptable findings, add vulnerability IDs to .pip-audit-suppressions.txt"
        exit 1
    }
else
    # Run without suppressions if file doesn't exist
    "${VENV_DIR}/bin/pip-audit" -r "${TEMP_REQ}" || {
        echo "⚠️  Security scan found vulnerabilities (see above)"
        echo "To suppress known/acceptable findings, create .pip-audit-suppressions.txt with vulnerability IDs"
        exit 1
    }
fi

echo "✓ Security scan passed (no high/critical vulnerabilities)"
