#!/usr/bin/env bash
set -euo pipefail

# compile-deps.sh - Compile pinned dependency lock files from .in sources
# This script uses pip-tools to generate deterministic lock files

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

# Compile each requirements file
echo "Compiling server/requirements.txt from server/requirements.in..."
"${VENV_DIR}/bin/pip-compile" --quiet --strip-extras --output-file=server/requirements.txt server/requirements.in

echo "Compiling harness/requirements.txt from harness/requirements.in..."
"${VENV_DIR}/bin/pip-compile" --quiet --strip-extras --output-file=harness/requirements.txt harness/requirements.in

echo "Compiling requirements-dev.txt from requirements-dev.in..."
"${VENV_DIR}/bin/pip-compile" --quiet --strip-extras --output-file=requirements-dev.txt requirements-dev.in

echo "✓ All lock files compiled successfully"
