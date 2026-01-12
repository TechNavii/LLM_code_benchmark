# SLSA Build Provenance Attestations

This document describes the SLSA (Supply-chain Levels for Software Artifacts) build provenance attestation system implemented in this repository.

## What is SLSA Provenance?

SLSA provenance is a cryptographically signed attestation that describes how software artifacts were built. It provides supply-chain security by enabling verification that:

1. Artifacts were built from the expected source code
2. Artifacts were built by an authorized build system
3. The build process was not tampered with

This repository implements SLSA Level 1-2 provenance for critical artifacts.

## Attested Artifacts

The following artifacts receive build provenance attestations:

| Artifact | Description | Location |
|----------|-------------|----------|
| `sbom.json` | Software Bill of Materials (CycloneDX) | `docs/sbom/sbom.json` |
| `server-requirements.txt` | Server lockfile with hashes | `server/requirements.txt` |
| `harness-requirements.txt` | Harness lockfile with hashes | `harness/requirements.txt` |
| `requirements-dev.txt` | Dev tools lockfile with hashes | `requirements-dev.txt` |

## When Attestations Are Generated

Provenance attestations are generated:

- **On push to main/master**: When lockfiles or SBOM-related files change
- **Weekly (Mondays 5AM UTC)**: Scheduled refresh to ensure freshness
- **Manual trigger**: Via workflow_dispatch for ad-hoc attestation

## Provenance Format

Attestations follow the [in-toto attestation specification](https://github.com/in-toto/attestation) with SLSA provenance v1 predicate:

```json
{
  "_type": "https://in-toto.io/Statement/v0.1",
  "subject": [
    {
      "name": "sbom.json",
      "digest": {
        "sha256": "<artifact-hash>"
      }
    }
  ],
  "predicateType": "https://slsa.dev/provenance/v1",
  "predicate": {
    "buildDefinition": {
      "buildType": "https://github.com/slsa-framework/slsa-github-generator/generic@v2",
      "externalParameters": {
        "workflow": ".github/workflows/slsa-provenance.yml"
      }
    },
    "runDetails": {
      "builder": {
        "id": "https://github.com/<owner>/<repo>/actions/runs/<run_id>"
      },
      "metadata": {
        "invocationId": "<workflow-run-url>",
        "startedOn": "<timestamp>"
      }
    }
  }
}
```

## Verifying Attestations

### Using GitHub CLI

```bash
# Verify an artifact's attestation
gh attestation verify <artifact-path> --owner <repo-owner>

# Example: Verify SBOM
gh attestation verify docs/sbom/sbom.json --owner your-org

# List attestations for an artifact
gh attestation list --owner <repo-owner> --repo <repo-name>
```

### Manual Verification

1. Download the provenance bundle from CI artifacts
2. Verify the SHA256 checksums match
3. Validate the provenance JSON structure

```bash
# Verify checksums
cd .attestation-artifacts
sha256sum -c checksums.sha256

# Validate JSON structure
python3 -c "
import json
with open('provenance/provenance.json') as f:
    data = json.load(f)
    assert '_type' in data
    assert 'subject' in data
    assert 'predicateType' in data
    print('Provenance is valid')
"
```

## CI Artifacts

Each provenance run produces these artifacts:

| Artifact | Contents | Retention |
|----------|----------|-----------|
| `slsa-provenance-<sha>` | All attested artifacts + checksums + provenance bundle | 90 days |
| `sbom-attested-<sha>` | SBOM with provenance metadata | 90 days |

## GitHub Attestation Storage

Attestations are stored in GitHub's attestation registry:

- **API**: `https://api.github.com/repos/<owner>/<repo>/attestations`
- **CLI**: `gh attestation list --owner <owner> --repo <repo>`
- **UI**: Repository Security tab (if available)

## Verification in CI

The verification job runs after attestation generation and:

1. Validates provenance bundle JSON structure
2. Verifies all checksums match
3. Attempts `gh attestation verify` for each artifact

## Brownfield Adoption

This feature is implemented in warn-only mode initially:

- Attestation failures do not block the workflow
- Verification failures are logged but don't fail the job
- Once proven stable, strict enforcement can be enabled

## Permissions Required

The workflow requires specific GitHub token permissions:

```yaml
permissions:
  contents: read      # Checkout code
  id-token: write     # OIDC-based signing
  attestations: write # Submit attestations to GitHub
```

## SLSA Level Achieved

| Requirement | Status | Notes |
|-------------|--------|-------|
| **Level 1** | ✅ | Provenance exists and is machine-readable |
| **Level 2** | ✅ | Build runs on hosted infrastructure (GitHub Actions) |
| **Level 3** | ⚠️ | Would require hardened build isolation |
| **Level 4** | ❌ | Requires hermetic builds + 2-party review |

Current implementation achieves **SLSA Level 2** with provenance.

## Related Documentation

- [SLSA Framework](https://slsa.dev/)
- [in-toto Attestation Spec](https://github.com/in-toto/attestation)
- [GitHub Attestations](https://docs.github.com/en/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds)
- [SBOM Documentation](./SBOM.md)
- [Security Documentation](./SECURITY.md)
- [Workflow Permissions](./WORKFLOW-PERMISSIONS.md)

## Troubleshooting

### Attestation Not Available

If `gh attestation verify` fails with "attestation not found":

1. Check if the workflow completed successfully
2. Verify you're checking the correct commit SHA
3. Ensure the attestations feature is enabled for the repository
4. Wait a few minutes for attestation propagation

### Checksum Mismatch

If checksums don't match:

1. Verify you're using the same artifact version
2. Check if the artifact was modified after attestation
3. Re-run the provenance workflow to generate fresh attestations

### Permission Errors

If attestation creation fails with permission errors:

1. Verify `id-token: write` permission is set
2. Verify `attestations: write` permission is set
3. Ensure workflow is running on main repository (not fork)
