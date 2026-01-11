#!/usr/bin/env bash
set -euo pipefail

# format.sh - Auto-fix formatting issues (developer-only, not run in CI)
# This script ensures a virtualenv exists and runs ruff format to fix formatting

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

# Install dependencies if needed
echo "Ensuring dependencies are installed..."
"${VENV_DIR}/bin/pip" install -q --upgrade pip
"${VENV_DIR}/bin/pip" install -q -r server/requirements.txt
"${VENV_DIR}/bin/pip" install -q -r harness/requirements.txt
"${VENV_DIR}/bin/pip" install -q -r requirements-dev.txt

# Run ruff format to fix formatting issues
echo "Running ruff format..."
"${VENV_DIR}/bin/ruff" format server/ harness/ tests/ conftest.py

echo "✓ Formatting applied"
