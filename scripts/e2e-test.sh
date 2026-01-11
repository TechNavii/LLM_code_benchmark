#!/usr/bin/env bash
# Run end-to-end tests wiring harness CLI to server API.
#
# These tests verify the full integration between FastAPI server and harness
# using mock model responses (no real LLM calls required).
#
# Usage:
#   ./scripts/e2e-test.sh           # Run E2E tests
#   ./scripts/e2e-test.sh -v        # Verbose output
#   ./scripts/e2e-test.sh --debug   # Debug mode (pdb on failure)

set -euo pipefail

cd "$(dirname "$0")/.."

# Ensure virtualenv exists
if [ ! -d ".venv" ]; then
    echo "Creating virtualenv..."
    python3 -m venv .venv
fi

# Ensure deps are installed
if [ ! -f ".venv/deps_installed" ]; then
    echo "Installing dependencies..."
    .venv/bin/pip install -q -r requirements-dev.txt
    touch .venv/deps_installed
fi

# Collect extra pytest args
PYTEST_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --debug)
            PYTEST_ARGS+=("--pdb")
            shift
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

# Run E2E tests with the e2e marker
# These tests start a real server process and make HTTP requests
echo "Running E2E tests..."
exec .venv/bin/pytest tests/test_harness_server_e2e.py -v --tb=short "${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"}"
