#!/usr/bin/env bash
set -euo pipefail

# check-deps.sh - Verify that lock files are up to date with .in sources
# This script fails if any lock file is out of sync with its .in file

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
trap "rm -rf ${TEMP_DIR}" EXIT

echo "Checking if lock files are up to date..."

# Compile to temporary files
"${VENV_DIR}/bin/pip-compile" --quiet --strip-extras --output-file="${TEMP_DIR}/server-requirements.txt" server/requirements.in
"${VENV_DIR}/bin/pip-compile" --quiet --strip-extras --output-file="${TEMP_DIR}/harness-requirements.txt" harness/requirements.in
"${VENV_DIR}/bin/pip-compile" --quiet --strip-extras --output-file="${TEMP_DIR}/dev-requirements.txt" requirements-dev.in

# Compare with existing lock files (ignoring header comments with pip-compile command)
# We filter out the comment line containing "pip-compile --output-file=" as it includes
# temporary paths that differ between runs
CHANGES=0

if ! diff <(grep -v "^#    pip-compile --output-file=" server/requirements.txt) \
         <(grep -v "^#    pip-compile --output-file=" "${TEMP_DIR}/server-requirements.txt") \
         >/dev/null 2>&1; then
    echo "❌ server/requirements.txt is out of date"
    CHANGES=1
fi

if ! diff <(grep -v "^#    pip-compile --output-file=" harness/requirements.txt) \
         <(grep -v "^#    pip-compile --output-file=" "${TEMP_DIR}/harness-requirements.txt") \
         >/dev/null 2>&1; then
    echo "❌ harness/requirements.txt is out of date"
    CHANGES=1
fi

if ! diff <(grep -v "^#    pip-compile --output-file=" requirements-dev.txt) \
         <(grep -v "^#    pip-compile --output-file=" "${TEMP_DIR}/dev-requirements.txt") \
         >/dev/null 2>&1; then
    echo "❌ requirements-dev.txt is out of date"
    CHANGES=1
fi

if [ ${CHANGES} -eq 1 ]; then
    echo ""
    echo "Lock files are out of date. Please run: ./scripts/compile-deps.sh"
    exit 1
fi

echo "✓ All lock files are up to date"
