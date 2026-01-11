#!/usr/bin/env bash
set -euo pipefail

# test.sh - Run test suite for the benchmark repository
# This script ensures a virtualenv exists and runs pytest on repository tests only

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
"${VENV_DIR}/bin/pip" install -q -r server/requirements.txt
"${VENV_DIR}/bin/pip" install -q -r harness/requirements.txt
"${VENV_DIR}/bin/pip" install -q -r requirements-dev.txt

# Run pytest (pytest.ini defines testpaths = tests harness/tests)
echo "Running pytest..."
"${VENV_DIR}/bin/pytest" "$@"

echo "✓ Tests passed"
