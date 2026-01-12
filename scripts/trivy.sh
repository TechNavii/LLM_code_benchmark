#!/usr/bin/env bash
set -euo pipefail

# trivy.sh - Run Trivy security scanning for filesystem and devcontainer
# This script scans for vulnerabilities, misconfigurations, and secrets
#
# Usage:
#   ./scripts/trivy.sh              # Run all scans (filesystem + Dockerfile)
#   ./scripts/trivy.sh --fs         # Run filesystem scan only
#   ./scripts/trivy.sh --dockerfile # Run Dockerfile scan only
#   ./scripts/trivy.sh --json       # Output JSON reports
#   ./scripts/trivy.sh --warn-only  # Exit 0 even on findings (for brownfield adoption)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Parse arguments
SCAN_FS=false
SCAN_DOCKERFILE=false
JSON_OUTPUT=false
WARN_ONLY="${TRIVY_WARN_ONLY:-false}"

# If no specific scan type is provided, run all scans
if [[ $# -eq 0 ]]; then
    SCAN_FS=true
    SCAN_DOCKERFILE=true
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fs)
            SCAN_FS=true
            shift
            ;;
        --dockerfile)
            SCAN_DOCKERFILE=true
            shift
            ;;
        --json)
            JSON_OUTPUT=true
            shift
            ;;
        --warn-only)
            WARN_ONLY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --fs           Run filesystem scan only"
            echo "  --dockerfile   Run Dockerfile scan only"
            echo "  --json         Output JSON reports to .trivy-reports/"
            echo "  --warn-only    Exit 0 even on findings (brownfield mode)"
            echo "  --help         Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  TRIVY_WARN_ONLY=true    Same as --warn-only"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check if trivy is available
if ! command -v trivy &>/dev/null; then
    echo "Trivy is not installed."
    echo ""
    echo "Install Trivy:"
    echo "  macOS:   brew install trivy"
    echo "  Linux:   curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin"
    echo "  Docker:  docker run aquasec/trivy"
    echo ""
    echo "See https://aquasecurity.github.io/trivy/latest/getting-started/installation/"
    exit 1
fi

echo "Running Trivy security scans..."
echo "Trivy version: $(trivy --version | head -1)"
echo ""

# Create reports directory if JSON output is enabled
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    mkdir -p "${REPO_ROOT}/.trivy-reports"
fi

# Track overall exit status
EXIT_STATUS=0

# Define exclusion patterns matching meta.excludePatterns
# These are passed as .trivyignore patterns
TRIVYIGNORE="${REPO_ROOT}/.trivyignore"

# ==========================================
# Filesystem Scan
# ==========================================
if [[ "${SCAN_FS}" == "true" ]]; then
    echo "=========================================="
    echo "Filesystem Vulnerability Scan"
    echo "=========================================="
    echo "Scanning for vulnerabilities in packages and misconfigurations..."
    echo ""

    # Common trivy args for filesystem scan
    # Exclusions matching meta.excludePatterns
    FS_ARGS=(
        fs
        --scanners "vuln,misconfig,secret"
        --severity "HIGH,CRITICAL"
        --skip-dirs "runs"
        --skip-dirs "tasks"
        --skip-dirs ".venv"
        --skip-dirs ".pytest_cache"
        --skip-dirs "__pycache__"
        --skip-dirs "node_modules"
        --skip-dirs ".git"
        --skip-dirs "htmlcov"
        --skip-dirs ".benchmarks"
        --skip-dirs ".fuzz-reports"
        --skip-dirs ".trivy-reports"
        --skip-dirs ".security-reports"
        --ignorefile "${TRIVYIGNORE}"
    )

    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        FS_ARGS+=(--format json --output "${REPO_ROOT}/.trivy-reports/fs-scan.json")
    else
        FS_ARGS+=(--format table)
    fi

    # Run filesystem scan
    if trivy "${FS_ARGS[@]}" "${REPO_ROOT}"; then
        echo ""
        echo "Filesystem scan completed (no high/critical findings)"
    else
        FS_EXIT=$?
        echo ""
        echo "Filesystem scan found issues (exit code: ${FS_EXIT})"
        if [[ "${WARN_ONLY}" != "true" ]]; then
            EXIT_STATUS=1
        fi
    fi
fi

# ==========================================
# Dockerfile Scan
# ==========================================
if [[ "${SCAN_DOCKERFILE}" == "true" ]]; then
    echo ""
    echo "=========================================="
    echo "Devcontainer Dockerfile Scan"
    echo "=========================================="

    DOCKERFILE_PATH="${REPO_ROOT}/.devcontainer/Dockerfile"

    if [[ ! -f "${DOCKERFILE_PATH}" ]]; then
        echo "Dockerfile not found at ${DOCKERFILE_PATH}"
        echo "Skipping Dockerfile scan (devcontainer is optional)"
    else
        echo "Scanning Dockerfile for misconfigurations and CVEs..."
        echo ""

        # Trivy args for config scan (Dockerfile best practices)
        CONFIG_ARGS=(
            config
            --severity "HIGH,CRITICAL"
            --ignorefile "${TRIVYIGNORE}"
        )

        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            CONFIG_ARGS+=(--format json --output "${REPO_ROOT}/.trivy-reports/dockerfile-config.json")
        else
            CONFIG_ARGS+=(--format table)
        fi

        # Run config scan on Dockerfile
        if trivy "${CONFIG_ARGS[@]}" "${DOCKERFILE_PATH}"; then
            echo ""
            echo "Dockerfile config scan completed (no high/critical findings)"
        else
            CONFIG_EXIT=$?
            echo ""
            echo "Dockerfile config scan found issues (exit code: ${CONFIG_EXIT})"
            if [[ "${WARN_ONLY}" != "true" ]]; then
                EXIT_STATUS=1
            fi
        fi

        # Also scan the base image for OS package CVEs
        echo ""
        echo "Scanning base image for OS package CVEs..."
        echo ""

        # Extract base image from Dockerfile
        BASE_IMAGE=$(grep "^FROM" "${DOCKERFILE_PATH}" | head -1 | awk '{print $2}')
        if [[ -n "${BASE_IMAGE}" ]]; then
            IMAGE_ARGS=(
                image
                --severity "HIGH,CRITICAL"
                --ignore-unfixed
                --ignorefile "${TRIVYIGNORE}"
            )

            if [[ "${JSON_OUTPUT}" == "true" ]]; then
                IMAGE_ARGS+=(--format json --output "${REPO_ROOT}/.trivy-reports/base-image.json")
            else
                IMAGE_ARGS+=(--format table)
            fi

            # Run image scan (may require Docker daemon for some images)
            if trivy "${IMAGE_ARGS[@]}" "${BASE_IMAGE}" 2>/dev/null; then
                echo ""
                echo "Base image scan completed"
            else
                IMAGE_EXIT=$?
                # Image scan may fail if Docker is not available or image not cached
                if [[ ${IMAGE_EXIT} -eq 1 ]]; then
                    echo ""
                    echo "Base image scan found vulnerabilities"
                    if [[ "${WARN_ONLY}" != "true" ]]; then
                        EXIT_STATUS=1
                    fi
                else
                    echo ""
                    echo "Base image scan skipped (Docker may not be available or image not cached)"
                    echo "To scan the base image, run: docker pull ${BASE_IMAGE} && trivy image ${BASE_IMAGE}"
                fi
            fi
        fi
    fi
fi

# ==========================================
# Summary
# ==========================================
echo ""
echo "=========================================="
echo "Trivy Scan Summary"
echo "=========================================="

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    echo "JSON reports saved to: ${REPO_ROOT}/.trivy-reports/"
    ls -la "${REPO_ROOT}/.trivy-reports/" 2>/dev/null || true
fi

if [[ ${EXIT_STATUS} -eq 0 ]]; then
    echo ""
    echo "All Trivy scans passed (no high/critical findings)"
else
    echo ""
    echo "Trivy found security issues that need attention"
    echo ""
    echo "To suppress known/acceptable findings, add them to .trivyignore"
    echo "See docs/SECURITY.md for suppression guidelines"
fi

exit ${EXIT_STATUS}
