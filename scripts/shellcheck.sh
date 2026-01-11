#!/usr/bin/env bash
set -euo pipefail

# Run ShellCheck for scripts/ to catch portability bugs
# This script scans shell scripts for common issues and portability problems

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

echo "Running ShellCheck on scripts/*.sh..."

# Check if shellcheck is available
if ! command -v shellcheck &> /dev/null; then
    echo "ShellCheck is not installed."
    echo "Install it via:"
    echo "  macOS: brew install shellcheck"
    echo "  Linux: apt-get install shellcheck"
    echo "  Or use the CI workflow which has ShellCheck pre-installed."
    exit 1
fi

# Run ShellCheck on all shell scripts in scripts/
# -e SC1091: Exclude "not following" warnings for dynamically sourced files
#            (check-python-version.sh, venv/bin/activate are resolved at runtime)
# -S warning: Set severity to warning (ignore info-level messages)
shellcheck -e SC1091 -S warning scripts/*.sh

echo "✓ ShellCheck passed"
