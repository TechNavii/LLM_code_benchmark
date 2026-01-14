#!/usr/bin/env bash
set -euo pipefail

# lint.sh - Run linting checks for the benchmark repository
# This script ensures a virtualenv exists and runs ruff for linting

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

# Install dependencies with hash verification
echo "Ensuring dependencies are installed (with hash verification)..."
"${VENV_DIR}/bin/pip" install -q --upgrade pip
"${VENV_DIR}/bin/pip" install -q --require-hashes -r server/requirements.txt
"${VENV_DIR}/bin/pip" install -q --require-hashes -r harness/requirements.txt
"${VENV_DIR}/bin/pip" install -q --require-hashes -r requirements-dev.txt

# Run ruff format check (check-only mode for CI)
echo "Running ruff format check..."
"${VENV_DIR}/bin/ruff" format --check server/ harness/ tests/ conftest.py

# Run ruff linting
echo "Running ruff check..."
"${VENV_DIR}/bin/ruff" check server/ harness/ tests/ conftest.py

echo "✓ Lint checks passed"
