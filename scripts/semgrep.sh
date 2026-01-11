#!/usr/bin/env bash
# Run Semgrep lightweight security scanning on server/, harness/, and gui/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# Check Python version
source "$SCRIPT_DIR/check-python-version.sh"

# Ensure virtualenv exists and dependencies are installed
if [ ! -d ".venv" ]; then
  echo "Creating virtualenv..."
  python -m venv .venv
fi

echo "Ensuring dependencies are installed..."
.venv/bin/pip install -q -r requirements-dev.txt

echo "Running Semgrep security scan..."
# Run Semgrep with custom rules, excluding tasks/* and other generated artifacts
.venv/bin/semgrep scan \
  --config .semgrep.yml \
  --exclude 'tasks/' \
  --exclude 'runs/' \
  --exclude '.venv/' \
  --exclude '.pytest_cache/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --metrics off \
  --quiet \
  server/ harness/ gui/

echo "✓ Semgrep scan passed"
