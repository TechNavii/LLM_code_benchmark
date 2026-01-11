#!/usr/bin/env bash
set -euo pipefail

# diff-cover.sh - Run diff coverage analysis on changed files
# This script compares coverage of changed files against a base branch
# to ensure new/changed code has adequate test coverage.

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
"${VENV_DIR}/bin/pip" install -q -r requirements-dev.txt

# Default values
COMPARE_BRANCH="${COMPARE_BRANCH:-origin/main}"
FAIL_UNDER="${DIFF_COVER_FAIL_UNDER:-0}"
HTML_REPORT="${DIFF_COVER_HTML:-}"
WARN_ONLY="${DIFF_COVER_WARN_ONLY:-false}"

# Check if coverage.xml exists
if [ ! -f "coverage.xml" ]; then
    echo "Error: coverage.xml not found. Run tests with coverage first:"
    echo "  ./scripts/test.sh"
    exit 1
fi

# Build diff-cover command
DIFF_COVER_ARGS=(
    "coverage.xml"
    "--compare-branch=${COMPARE_BRANCH}"
    "--exclude" "tasks/*"
    "--exclude" "runs/*"
    "--exclude" ".venv/*"
    "--exclude" "__pycache__/*"
)

# Add fail-under threshold if set
if [ "${FAIL_UNDER}" != "0" ]; then
    DIFF_COVER_ARGS+=("--fail-under=${FAIL_UNDER}")
fi

# Add HTML report if requested
if [ -n "${HTML_REPORT}" ]; then
    DIFF_COVER_ARGS+=("--html-report=${HTML_REPORT}")
fi

echo "Running diff-cover against ${COMPARE_BRANCH}..."
echo "Excluding: tasks/*, runs/*, .venv/*, __pycache__/*"

if [ "${WARN_ONLY}" = "true" ]; then
    # Warn-only mode: run but don't fail on coverage threshold
    "${VENV_DIR}/bin/diff-cover" "${DIFF_COVER_ARGS[@]}" || {
        echo ""
        echo "⚠ Diff coverage did not meet threshold (warn-only mode)"
        exit 0
    }
else
    "${VENV_DIR}/bin/diff-cover" "${DIFF_COVER_ARGS[@]}"
fi

echo ""
echo "✓ Diff coverage analysis complete"
