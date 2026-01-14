#!/usr/bin/env bash
set -euo pipefail

# check-deps.sh - Verify that lock files are up to date with .in sources
# This script fails if any lock file is out of sync with its .in file
# Also validates that lock files contain hashes for dependency integrity

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

cd "${REPO_ROOT}"

# Check Python version meets requirements
source "${SCRIPT_DIR}/check-python-version.sh"
check_python_version python3

# Ensure virtualenv exists
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtualenv at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
fi

# Install pip-tools
echo "Ensuring pip-tools is installed..."
"${VENV_DIR}/bin/pip" install -q --upgrade pip
"${VENV_DIR}/bin/pip" install -q pip-tools

# Create temporary directory for compiled files
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "${TEMP_DIR}"' EXIT

echo "Checking if lock files are up to date..."

# Common pip-compile flags (must match compile-deps.sh)
COMPILE_FLAGS="--quiet --strip-extras --generate-hashes --allow-unsafe"

# Compile without modifying tracked files.
# Note: pip-compile prints the generated requirements to STDERR in --dry-run mode.
"${VENV_DIR}/bin/pip-compile" ${COMPILE_FLAGS} --dry-run --output-file=server/requirements.txt server/requirements.in 1>/dev/null 2>"${TEMP_DIR}/server-requirements.txt"
"${VENV_DIR}/bin/pip-compile" ${COMPILE_FLAGS} --dry-run --output-file=harness/requirements.txt harness/requirements.in 1>/dev/null 2>"${TEMP_DIR}/harness-requirements.txt"
"${VENV_DIR}/bin/pip-compile" ${COMPILE_FLAGS} --dry-run --output-file=requirements-dev.txt requirements-dev.in 1>/dev/null 2>"${TEMP_DIR}/dev-requirements.txt"

strip_pip_compile_header() {
    awk 'BEGIN{started=0} started{print; next} /^[[:space:]]*$/{next} /^#/{next} {started=1; print}' "$1"
}

CHANGES=0

if ! diff <(strip_pip_compile_header server/requirements.txt) <(strip_pip_compile_header "${TEMP_DIR}/server-requirements.txt") >/dev/null 2>&1; then
    echo "❌ server/requirements.txt is out of date"
    CHANGES=1
fi

if ! diff <(strip_pip_compile_header harness/requirements.txt) <(strip_pip_compile_header "${TEMP_DIR}/harness-requirements.txt") >/dev/null 2>&1; then
    echo "❌ harness/requirements.txt is out of date"
    CHANGES=1
fi

if ! diff <(strip_pip_compile_header requirements-dev.txt) <(strip_pip_compile_header "${TEMP_DIR}/dev-requirements.txt") >/dev/null 2>&1; then
    echo "❌ requirements-dev.txt is out of date"
    CHANGES=1
fi

if [ ${CHANGES} -eq 1 ]; then
    echo ""
    echo "Lock files are out of date. Please run: ./scripts/compile-deps.sh"
    exit 1
fi

echo "✓ All lock files are up to date"
