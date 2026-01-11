#!/usr/bin/env bash
# Run Bandit SAST scanning on server/ and harness/

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

echo "Running Bandit SAST scan..."
.venv/bin/bandit -c .bandit.yml -r server/ harness/

echo "✓ Bandit scan passed"
