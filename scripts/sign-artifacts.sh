#!/usr/bin/env bash
set -euo pipefail

# sign-artifacts.sh - Sign critical artifacts using Sigstore cosign (keyless)
# This script signs SBOMs and lockfiles with Sigstore keyless signing via GitHub OIDC.
#
# Keyless signing uses Fulcio (CA) and Rekor (transparency log) from the Sigstore
# public good infrastructure. In CI, authentication is via GitHub OIDC; locally,
# it will prompt for browser-based authentication.
#
# Usage:
#   ./scripts/sign-artifacts.sh              # Sign all artifacts
#   ./scripts/sign-artifacts.sh --verify     # Verify existing signatures
#   ./scripts/sign-artifacts.sh --ci         # Run in CI mode (non-interactive)
#
# Environment:
#   COSIGN_EXPERIMENTAL=1  - Required for keyless signing (set automatically)
#   GITHUB_ACTIONS         - Detected automatically for CI mode

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
VERIFY_ONLY=false
CI_MODE=false
WARN_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --verify)
            VERIFY_ONLY=true
            shift
            ;;
        --ci)
            CI_MODE=true
            shift
            ;;
        --warn-only)
            WARN_ONLY=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --verify      Verify existing signatures only (don't sign)"
            echo "  --ci          Run in CI mode (non-interactive)"
            echo "  --warn-only   Don't fail on errors (brownfield mode)"
            echo "  -h, --help    Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Auto-detect CI mode
if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
    CI_MODE=true
fi

# Enable keyless signing
export COSIGN_EXPERIMENTAL=1

# Check for cosign installation
if ! command -v cosign &> /dev/null; then
    echo -e "${RED}Error: cosign is not installed${NC}"
    echo ""
    echo "Install cosign:"
    echo "  macOS:   brew install cosign"
    echo "  Linux:   curl -O -L https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64"
    echo "           chmod +x cosign-linux-amd64 && sudo mv cosign-linux-amd64 /usr/local/bin/cosign"
    echo "  Or see:  https://docs.sigstore.dev/cosign/system_config/installation/"
    if [[ "${WARN_ONLY}" == "true" ]]; then
        echo -e "${YELLOW}Warning: Skipping signing (warn-only mode)${NC}"
        exit 0
    fi
    exit 1
fi

echo "Sigstore Artifact Signing"
echo "========================="
echo ""
echo "cosign version: $(cosign version 2>&1 | head -1 || echo 'unknown')"
echo "Mode: ${CI_MODE:+CI}${CI_MODE:-local}"
echo ""

# Define artifacts to sign
ARTIFACTS=(
    "docs/sbom/sbom.json"
    "server/requirements.txt"
    "harness/requirements.txt"
    "requirements-dev.txt"
)

# Create signatures directory
SIGNATURES_DIR="${REPO_ROOT}/.signatures"
mkdir -p "${SIGNATURES_DIR}"

# OIDC issuer for verification (GitHub Actions)
OIDC_ISSUER="https://token.actions.githubusercontent.com"

sign_artifact() {
    local artifact="$1"
    local artifact_path="${REPO_ROOT}/${artifact}"
    local artifact_name
    artifact_name=$(basename "${artifact}")
    local sig_path="${SIGNATURES_DIR}/${artifact_name}.sig"
    local cert_path="${SIGNATURES_DIR}/${artifact_name}.cert"

    if [[ ! -f "${artifact_path}" ]]; then
        echo -e "${YELLOW}Warning: Artifact not found: ${artifact}${NC}"
        return 1
    fi

    echo "Signing: ${artifact}"

    # Sign the artifact with keyless signing
    # --bundle creates a bundle file containing signature, certificate, and transparency log entry
    # --yes skips confirmation prompts (for CI)
    if [[ "${CI_MODE}" == "true" ]]; then
        # CI mode: Use OIDC identity provider
        if cosign sign-blob \
            --yes \
            --bundle "${SIGNATURES_DIR}/${artifact_name}.bundle" \
            --output-signature "${sig_path}" \
            --output-certificate "${cert_path}" \
            "${artifact_path}" 2>&1; then
            echo -e "${GREEN}  Signed successfully${NC}"
            echo "  Signature: ${sig_path}"
            echo "  Certificate: ${cert_path}"
            echo "  Bundle: ${SIGNATURES_DIR}/${artifact_name}.bundle"
            return 0
        else
            echo -e "${RED}  Signing failed${NC}"
            return 1
        fi
    else
        # Local mode: Will prompt for browser authentication
        echo "  (Browser authentication may be required)"
        if cosign sign-blob \
            --bundle "${SIGNATURES_DIR}/${artifact_name}.bundle" \
            --output-signature "${sig_path}" \
            --output-certificate "${cert_path}" \
            "${artifact_path}" 2>&1; then
            echo -e "${GREEN}  Signed successfully${NC}"
            return 0
        else
            echo -e "${RED}  Signing failed${NC}"
            return 1
        fi
    fi
}

verify_artifact() {
    local artifact="$1"
    local artifact_path="${REPO_ROOT}/${artifact}"
    local artifact_name
    artifact_name=$(basename "${artifact}")
    local bundle_path="${SIGNATURES_DIR}/${artifact_name}.bundle"
    local sig_path="${SIGNATURES_DIR}/${artifact_name}.sig"
    local cert_path="${SIGNATURES_DIR}/${artifact_name}.cert"

    if [[ ! -f "${artifact_path}" ]]; then
        echo -e "${YELLOW}Warning: Artifact not found: ${artifact}${NC}"
        return 1
    fi

    echo "Verifying: ${artifact}"

    # Try bundle verification first (preferred)
    if [[ -f "${bundle_path}" ]]; then
        if [[ -n "${GITHUB_REPOSITORY:-}" ]]; then
            # In CI: verify with specific identity
            if cosign verify-blob \
                --bundle "${bundle_path}" \
                --certificate-identity-regexp "https://github.com/${GITHUB_REPOSITORY}/.github/workflows/.*" \
                --certificate-oidc-issuer "${OIDC_ISSUER}" \
                "${artifact_path}" 2>&1; then
                echo -e "${GREEN}  Verification passed (bundle)${NC}"
                return 0
            fi
        else
            # Local: verify without strict identity matching
            if cosign verify-blob \
                --bundle "${bundle_path}" \
                --certificate-identity-regexp ".*" \
                --certificate-oidc-issuer-regexp ".*" \
                "${artifact_path}" 2>&1; then
                echo -e "${GREEN}  Verification passed (bundle)${NC}"
                return 0
            fi
        fi
    fi

    # Fall back to signature + certificate verification
    if [[ -f "${sig_path}" ]] && [[ -f "${cert_path}" ]]; then
        if cosign verify-blob \
            --signature "${sig_path}" \
            --certificate "${cert_path}" \
            --certificate-identity-regexp ".*" \
            --certificate-oidc-issuer-regexp ".*" \
            "${artifact_path}" 2>&1; then
            echo -e "${GREEN}  Verification passed (sig+cert)${NC}"
            return 0
        fi
    fi

    echo -e "${RED}  Verification failed or no signature found${NC}"
    return 1
}

# Track results
SIGNED=0
FAILED=0
VERIFIED=0
VERIFY_FAILED=0

if [[ "${VERIFY_ONLY}" == "true" ]]; then
    echo "Verifying signatures..."
    echo ""

    for artifact in "${ARTIFACTS[@]}"; do
        if verify_artifact "${artifact}"; then
            ((VERIFIED++))
        else
            ((VERIFY_FAILED++))
        fi
        echo ""
    done

    echo "========================="
    echo "Verification Summary"
    echo "========================="
    echo "Verified: ${VERIFIED}"
    echo "Failed:   ${VERIFY_FAILED}"

    if [[ ${VERIFY_FAILED} -gt 0 ]]; then
        if [[ "${WARN_ONLY}" == "true" ]]; then
            echo -e "${YELLOW}Warning: Some verifications failed (warn-only mode)${NC}"
            exit 0
        fi
        exit 1
    fi
else
    echo "Signing artifacts..."
    echo ""

    for artifact in "${ARTIFACTS[@]}"; do
        if sign_artifact "${artifact}"; then
            ((SIGNED++))
        else
            ((FAILED++))
        fi
        echo ""
    done

    echo "========================="
    echo "Signing Summary"
    echo "========================="
    echo "Signed: ${SIGNED}"
    echo "Failed: ${FAILED}"
    echo ""
    echo "Signatures stored in: ${SIGNATURES_DIR}/"

    # List generated files
    if [[ -d "${SIGNATURES_DIR}" ]]; then
        echo ""
        echo "Generated files:"
        ls -la "${SIGNATURES_DIR}/" 2>/dev/null || true
    fi

    if [[ ${FAILED} -gt 0 ]]; then
        if [[ "${WARN_ONLY}" == "true" ]]; then
            echo -e "${YELLOW}Warning: Some signings failed (warn-only mode)${NC}"
            exit 0
        fi
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}Sigstore signing completed${NC}"
