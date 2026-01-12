#!/usr/bin/env bash
set -euo pipefail

# Lint Dockerfiles for security and best-practice issues using hadolint
# This script scans .devcontainer/Dockerfile for common issues
#
# Devcontainer remains optional - this check does not block non-container workflows

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

DOCKERFILE=".devcontainer/Dockerfile"

# Check if Dockerfile exists (devcontainer is optional)
if [[ ! -f "${DOCKERFILE}" ]]; then
    echo "No Dockerfile found at ${DOCKERFILE} - skipping hadolint (devcontainer is optional)"
    exit 0
fi

echo "Running hadolint on ${DOCKERFILE}..."

# Check if hadolint is available
if ! command -v hadolint &> /dev/null; then
    # Try running via Docker as fallback
    if command -v docker &> /dev/null; then
        echo "hadolint not found locally, using Docker..."
        docker run --rm -i hadolint/hadolint < "${DOCKERFILE}"
        echo "Hadolint passed"
        exit 0
    fi

    echo "hadolint is not installed."
    echo "Install it via:"
    echo "  macOS: brew install hadolint"
    echo "  Linux: Download from https://github.com/hadolint/hadolint/releases"
    echo "  Docker: docker run --rm -i hadolint/hadolint < Dockerfile"
    echo "  Or use the CI workflow which installs hadolint automatically."
    exit 1
fi

# Run hadolint with configuration file if present
HADOLINT_ARGS=()

# Use config file if present
if [[ -f ".hadolint.yaml" ]]; then
    HADOLINT_ARGS+=(--config .hadolint.yaml)
fi

# Run hadolint
# Exits non-zero if any warnings/errors found
hadolint "${HADOLINT_ARGS[@]}" "${DOCKERFILE}"

echo "Hadolint passed"
