#!/usr/bin/env bash
set -euo pipefail

# Run actionlint to validate GitHub Actions workflow files
# Catches YAML syntax errors, expression errors, and common mistakes early

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

WORKFLOW_DIR=".github/workflows"

# Check if workflow directory exists
if [[ ! -d "${WORKFLOW_DIR}" ]]; then
    echo "No workflow directory found at ${WORKFLOW_DIR}"
    echo "Skipping actionlint check."
    exit 0
fi

# Check if there are any workflow files
workflow_count=$(find "${WORKFLOW_DIR}" -name "*.yml" -o -name "*.yaml" 2>/dev/null | wc -l | tr -d ' ')
if [[ "${workflow_count}" -eq 0 ]]; then
    echo "No workflow files found in ${WORKFLOW_DIR}"
    echo "Skipping actionlint check."
    exit 0
fi

echo "Running actionlint on ${WORKFLOW_DIR}/*.yml..."

# Check if actionlint is available
if ! command -v actionlint &> /dev/null; then
    echo "actionlint is not installed."
    echo "Install it via:"
    echo "  macOS: brew install actionlint"
    echo "  Linux: Download from https://github.com/rhysd/actionlint/releases"
    echo "  Or use the CI workflow which installs actionlint automatically."
    echo ""
    echo "Skipping actionlint check (not installed locally)."
    echo "CI will validate workflows with actionlint."
    exit 0
fi

# Run actionlint on all workflow files
# -color: Enable colored output for better readability
# No special flags needed - actionlint has sensible defaults
if actionlint -color "${WORKFLOW_DIR}"/*.yml; then
    echo "actionlint passed - all workflows are valid"
else
    echo ""
    echo "actionlint found issues in workflow files."
    echo "Please fix the issues above before committing."
    exit 1
fi
