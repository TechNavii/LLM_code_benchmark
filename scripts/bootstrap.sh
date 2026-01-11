#!/usr/bin/env bash
set -euo pipefail

# bootstrap.sh - Set up local development environment for the benchmark repository
# This script creates a virtualenv, installs locked dependencies, and provides next steps.
# It is idempotent and works on macOS/Linux.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"

cd "${REPO_ROOT}"

# Check Python version meets requirements
source "${SCRIPT_DIR}/check-python-version.sh"
check_python_version python3

echo "=================================="
echo "Benchmark Harness Bootstrap Script"
echo "=================================="
echo ""

# Create virtualenv if it doesn't exist
if [ -d "${VENV_DIR}" ]; then
    echo "Virtualenv already exists at ${VENV_DIR}"
else
    echo "Creating virtualenv at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
    echo "✓ Virtualenv created"
fi

# Upgrade pip to latest version
echo ""
echo "Upgrading pip..."
"${VENV_DIR}/bin/pip" install --upgrade pip --quiet

# Install locked dependencies with hash verification (same as CI validators)
# --require-hashes ensures package integrity via SHA256 hash verification
echo ""
echo "Installing locked dependencies (with hash verification)..."
echo "  - server/requirements.txt (server runtime deps)"
"${VENV_DIR}/bin/pip" install -r server/requirements.txt --require-hashes --quiet
echo "  - harness/requirements.txt (harness runtime deps)"
"${VENV_DIR}/bin/pip" install -r harness/requirements.txt --require-hashes --quiet
echo "  - requirements-dev.txt (dev/test tooling)"
"${VENV_DIR}/bin/pip" install -r requirements-dev.txt --require-hashes --quiet
echo "✓ Dependencies installed (hash-verified)"

# Install pre-commit hooks (optional but recommended)
echo ""
echo "Setting up pre-commit hooks..."
if "${VENV_DIR}/bin/pre-commit" install 2>/dev/null; then
    echo "✓ Pre-commit hooks installed"
else
    echo "⚠ Pre-commit hooks not installed (run '.venv/bin/pre-commit install' manually)"
fi

# Verify installation by checking key tools
echo ""
echo "Verifying installation..."
TOOLS_OK=true
for tool in pytest ruff mypy vulture bandit; do
    if "${VENV_DIR}/bin/${tool}" --version >/dev/null 2>&1; then
        echo "  ✓ ${tool} available"
    else
        echo "  ✗ ${tool} not found"
        TOOLS_OK=false
    fi
done

if [ "${TOOLS_OK}" = "true" ]; then
    echo ""
    echo "✓ Bootstrap complete!"
else
    echo ""
    echo "⚠ Bootstrap completed with warnings. Some tools may not be available."
fi

# Print next steps
echo ""
echo "=================================="
echo "Next Steps"
echo "=================================="
echo ""
echo "1. Activate the virtualenv:"
echo "   source .venv/bin/activate"
echo ""
echo "2. Run validators to verify your setup:"
echo "   ./scripts/lint.sh      # Check code formatting and linting"
echo "   ./scripts/typecheck.sh # Run type checking"
echo "   ./scripts/test.sh      # Run the test suite"
echo ""
echo "3. Start the development server:"
echo "   ./scripts/devserver.sh      # Main benchmark server"
echo "   ./scripts/devserver_qa.sh   # QA server"
echo ""
echo "4. (Optional) Set up your .env file:"
echo "   cp .env.example .env"
echo "   # Edit .env with your API keys and settings"
echo ""
echo "For more information, see docs/DEVELOPMENT.md"
echo ""
