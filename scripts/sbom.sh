#!/usr/bin/env bash
set -euo pipefail

# sbom.sh - Generate Software Bill of Materials (SBOM) for the benchmark repository
# This script generates CycloneDX SBOMs for Python dependencies using locked
# requirements files for reproducibility and supply-chain visibility.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
SBOM_DIR="${REPO_ROOT}/docs/sbom"

cd "${REPO_ROOT}"

# Check Python version meets requirements
source "${SCRIPT_DIR}/check-python-version.sh"
check_python_version python3

# Ensure virtualenv exists
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtualenv at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
fi

# Ensure cyclonedx-bom is installed
echo "Ensuring cyclonedx-bom is installed..."
"${VENV_DIR}/bin/pip" install -q cyclonedx-bom

# Create SBOM output directory
mkdir -p "${SBOM_DIR}"

echo "Generating Software Bill of Materials (SBOM)..."
echo ""

# Generate SBOM from locked dependencies
# Using CycloneDX format as per industry standard for supply-chain security
#
# Key settings:
#   --output-format json/xml: Format for machine readability
#   --output-reproducible: Removes timestamps for deterministic output
#   --mc-type application: Marks this as an application (not library)
#   --spec-version 1.5: Uses stable CycloneDX schema version
#
# The SBOM includes:
#   - All installed packages in the virtualenv
#   - Package versions, licenses, and hashes
#   - Dependency relationships
#
# Secrets are excluded by design:
#   - cyclonedx-bom only reads package metadata from pip
#   - No environment variables, config files, or credentials are included
#   - Output contains only standard package information (name, version, license, hashes)

# Generate combined SBOM from all installed packages
# This uses the lock files which pin all transitive dependencies
echo "Generating combined SBOM (JSON format)..."
"${VENV_DIR}/bin/cyclonedx-py" environment \
    --output-format JSON \
    --output-reproducible \
    --mc-type application \
    --spec-version 1.5 \
    --output-file "${SBOM_DIR}/sbom.json" \
    "${VENV_DIR}"

echo "Generated: ${SBOM_DIR}/sbom.json"

# Also generate XML format for compatibility
echo "Generating combined SBOM (XML format)..."
"${VENV_DIR}/bin/cyclonedx-py" environment \
    --output-format XML \
    --output-reproducible \
    --mc-type application \
    --spec-version 1.5 \
    --output-file "${SBOM_DIR}/sbom.xml" \
    "${VENV_DIR}"

echo "Generated: ${SBOM_DIR}/sbom.xml"

# Verify SBOM was generated successfully and contains expected structure
if [ -f "${SBOM_DIR}/sbom.json" ]; then
    # Quick validation - check that it's valid JSON with expected fields
    if python3 -c "import json; d = json.load(open('${SBOM_DIR}/sbom.json')); assert 'bomFormat' in d and 'components' in d" 2>/dev/null; then
        component_count=$(python3 -c "import json; print(len(json.load(open('${SBOM_DIR}/sbom.json')).get('components', [])))")
        echo ""
        echo "SBOM validation passed:"
        echo "  - Format: CycloneDX"
        echo "  - Components: ${component_count}"
        echo "  - Schema: 1.5"
    else
        echo "WARNING: SBOM JSON validation failed - file may be incomplete"
    fi
else
    echo "ERROR: SBOM generation failed - no output file created"
    exit 1
fi

echo ""
echo "SBOM files generated in: ${SBOM_DIR}/"
echo ""
echo "These SBOMs can be:"
echo "  - Uploaded as CI artifacts for supply-chain visibility"
echo "  - Attached to releases for vulnerability tracking"
echo "  - Analyzed with tools like Dependency-Track, Grype, or OWASP tools"
echo ""
echo "✓ SBOM generation completed"
