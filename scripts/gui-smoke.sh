#!/usr/bin/env bash
# Run GUI headless browser smoke tests using Playwright
#
# Usage:
#   ./scripts/gui-smoke.sh                     # Run GUI smoke tests
#   ./scripts/gui-smoke.sh --headed            # Run with visible browser
#   ./scripts/gui-smoke.sh --debug             # Run with Playwright debug mode
#
# Environment variables:
#   PLAYWRIGHT_BROWSER: Browser to use (chromium, firefox, webkit). Default: chromium
#   PLAYWRIGHT_HEADLESS: Set to "false" for visible browser. Default: true

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# Check Python version
source "$SCRIPT_DIR/check-python-version.sh"
check_python_version python3

# Ensure virtualenv exists and dependencies are installed
if [ ! -d ".venv" ]; then
    echo "Creating virtualenv..."
    python3 -m venv .venv
fi

echo "Ensuring dependencies are installed (with hash verification)..."
.venv/bin/pip install -q --require-hashes -r server/requirements.txt
.venv/bin/pip install -q --require-hashes -r requirements-dev.txt

# Install Playwright browsers if not already installed
if ! .venv/bin/playwright --version >/dev/null 2>&1; then
    echo "Installing Playwright..."
    .venv/bin/pip install -q pytest-playwright
fi

# Check if browsers are installed
if ! .venv/bin/python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.chromium.executable_path; p.stop()" 2>/dev/null; then
    echo "Installing Playwright browsers (chromium only for CI efficiency)..."
    .venv/bin/playwright install chromium
fi

# Parse command line arguments
PYTEST_ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --headed)
            export PLAYWRIGHT_HEADLESS=false
            shift
            ;;
        --debug)
            export PWDEBUG=1
            shift
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

echo "GUI Headless Browser Smoke Tests"
echo "================================="
echo "Browser: ${PLAYWRIGHT_BROWSER:-chromium}"
echo "Headless: ${PLAYWRIGHT_HEADLESS:-true}"
echo ""

# Run the GUI smoke tests
# Use pytest marker to select only GUI tests
exec .venv/bin/pytest tests/test_gui_smoke.py \
    -v \
    --tb=short \
    "${PYTEST_ARGS[@]+"${PYTEST_ARGS[@]}"}"
