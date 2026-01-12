# Software Bill of Materials (SBOM)

This document describes the SBOM generation process for the benchmark repository.

## Overview

The repository generates Software Bills of Materials (SBOMs) using the CycloneDX
format for supply-chain visibility and vulnerability tracking. SBOMs are generated
from the locked Python dependencies in the virtual environment.

## Generation

SBOMs are generated using `cyclonedx-bom` via the `scripts/sbom.sh` script:

```bash
./scripts/sbom.sh
```

This produces two files in `docs/sbom/`:
- `sbom.json` - JSON format (machine-readable)
- `sbom.xml` - XML format (for compatibility)

## CI Integration

SBOMs are automatically generated in the CI workflow and uploaded as artifacts
with 30-day retention. Each Python version in the matrix generates its own SBOM.

## Format Details

- **Standard**: CycloneDX 1.5
- **Component Type**: Application
- **Output**: Reproducible (no timestamps)

## What's Included

The SBOM includes:
- All Python packages installed in the virtual environment
- Package versions and licenses
- Package hashes (when available)
- Dependency relationships

## What's NOT Included

By design, the SBOM does NOT contain:
- Environment variables or secrets
- Configuration files
- Credentials or API keys
- Source code

## Using the SBOM

SBOMs can be used with various tools for supply-chain security:

### Vulnerability Scanning

```bash
# Using Grype
grype sbom:docs/sbom/sbom.json

# Using Trivy
trivy sbom docs/sbom/sbom.json
```

### Dependency-Track

Import the SBOM JSON into OWASP Dependency-Track for continuous monitoring:
1. Go to Projects > Create Project
2. Upload `docs/sbom/sbom.json`
3. Configure vulnerability analysis

### License Analysis

The CycloneDX SBOM includes license information that can be extracted:

```bash
# Using cyclonedx-cli
cyclonedx analyze --input-file docs/sbom/sbom.json
```

## Locked Dependencies

The SBOM is generated from the virtual environment which is populated from
locked requirements files:
- `server/requirements.txt` - Server dependencies
- `harness/requirements.txt` - Harness dependencies
- `requirements-dev.txt` - Development/test dependencies

These lock files pin all transitive dependencies for reproducibility.

## Updating the SBOM

To regenerate the SBOM after dependency changes:

1. Update lock files: `./scripts/compile-deps.sh`
2. Install dependencies: `./scripts/lint.sh` (or any validator script)
3. Regenerate SBOM: `./scripts/sbom.sh`

## Release Attachments

For releases, consider:
1. Including the SBOM as a release artifact
2. Publishing to a vulnerability database
3. Signing the SBOM for authenticity (future enhancement)
