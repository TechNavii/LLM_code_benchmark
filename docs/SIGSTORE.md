# Sigstore Artifact Signing

This document describes the Sigstore keyless signing implementation for critical artifacts in this repository.

## What is Sigstore?

[Sigstore](https://sigstore.dev/) is a free, open-source tool for signing software artifacts. It provides:

- **Keyless signing**: No need to manage private keys
- **Transparency**: Signatures are recorded in a public transparency log (Rekor)
- **Identity-based**: Uses existing identities (GitHub OIDC) for authentication

## How It Works

```
┌─────────────┐     ┌──────────┐     ┌─────────┐     ┌───────┐
│   GitHub    │────▶│  Fulcio  │────▶│  cosign │────▶│ Rekor │
│   OIDC      │     │   (CA)   │     │ (sign)  │     │ (log) │
└─────────────┘     └──────────┘     └─────────┘     └───────┘
                          │                               │
                          ▼                               ▼
                    Certificate                   Transparency
                    (short-lived)                 Log Entry
```

1. **Authentication**: GitHub Actions provides an OIDC token identifying the workflow
2. **Certificate**: Fulcio (Certificate Authority) issues a short-lived certificate
3. **Signing**: cosign signs the artifact using the certificate
4. **Transparency**: The signature is recorded in Rekor (transparency log)
5. **Bundle**: A bundle file is created containing signature + certificate + log entry

## Signed Artifacts

The following artifacts are signed with Sigstore:

| Artifact | Description | Location |
|----------|-------------|----------|
| `sbom.json` | Software Bill of Materials (CycloneDX) | `docs/sbom/sbom.json` |
| `server-requirements.txt` | Server lockfile with hashes | `server/requirements.txt` |
| `harness-requirements.txt` | Harness lockfile with hashes | `harness/requirements.txt` |
| `requirements-dev.txt` | Dev tools lockfile with hashes | `requirements-dev.txt` |

## When Signing Occurs

Sigstore signing runs as part of the SLSA Provenance workflow:

- **On push to main/master**: When lockfiles or SBOM-related files change
- **Weekly (Mondays 5AM UTC)**: Scheduled refresh for freshness
- **Manual trigger**: Via workflow_dispatch for ad-hoc signing

## Signature Bundle Format

Each signed artifact produces a `.bundle` file containing:

```json
{
  "base64Signature": "MEUCIQDx...",
  "cert": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----",
  "rekorBundle": {
    "logId": { "keyId": "wNI9atQ..." },
    "logIndex": 12345678,
    "integratedTime": 1704067200,
    "signedEntryTimestamp": "MEUCIQDy..."
  }
}
```

## Verifying Signatures

### Prerequisites

Install cosign:

```bash
# macOS
brew install cosign

# Linux
curl -O -L https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64
chmod +x cosign-linux-amd64
sudo mv cosign-linux-amd64 /usr/local/bin/cosign

# Or see: https://docs.sigstore.dev/cosign/system_config/installation/
```

### Using the Verification Script

```bash
# Verify all signatures locally
./scripts/sign-artifacts.sh --verify

# Verify in brownfield mode (warn only)
./scripts/sign-artifacts.sh --verify --warn-only
```

### Manual Verification

```bash
# Verify with specific identity (CI context)
cosign verify-blob \
  --bundle .signatures/sbom.json.bundle \
  --certificate-identity-regexp "https://github.com/YOUR_ORG/YOUR_REPO/.github/workflows/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  docs/sbom/sbom.json

# Verify with loose identity matching (local testing)
cosign verify-blob \
  --bundle .signatures/sbom.json.bundle \
  --certificate-identity-regexp ".*" \
  --certificate-oidc-issuer-regexp ".*" \
  docs/sbom/sbom.json
```

### From CI Artifacts

1. Download the `sigstore-signatures-<sha>` artifact from GitHub Actions
2. Download the `slsa-provenance-<sha>` artifact (contains the signed files)
3. Run verification:

```bash
# Extract artifacts
unzip sigstore-signatures-*.zip -d .signatures/
unzip slsa-provenance-*.zip -d .attestation-artifacts/

# Verify SBOM signature
cosign verify-blob \
  --bundle .signatures/sbom.json.bundle \
  --certificate-identity-regexp ".*" \
  --certificate-oidc-issuer-regexp ".*" \
  .attestation-artifacts/sbom.json
```

## CI Artifacts

Each signing run produces these artifacts:

| Artifact | Contents | Retention |
|----------|----------|-----------|
| `sigstore-signatures-<sha>` | `.sig`, `.cert`, and `.bundle` files | 90 days |
| `slsa-provenance-<sha>` | Signed artifacts + checksums + provenance | 90 days |

## Security Considerations

### What Sigstore Provides

- **Integrity**: Signatures prove artifacts haven't been modified
- **Authenticity**: Certificates prove artifacts came from this repository's workflows
- **Non-repudiation**: Rekor log provides immutable evidence of signing

### What Sigstore Does NOT Provide

- **Confidentiality**: Artifacts themselves are not encrypted
- **Access control**: Anyone can download and verify signatures
- **Key management**: Sigstore uses keyless signing (no private keys to manage)

### Certificate Identity

In CI, certificates are issued with identity claims:

```
Subject Alternative Name (SAN): https://github.com/OWNER/REPO/.github/workflows/slsa-provenance.yml@refs/heads/main
Issuer: https://token.actions.githubusercontent.com
```

Verification should check these claims to ensure signatures came from the expected workflow.

## Brownfield Adoption

This feature is implemented in warn-only mode initially:

- Signing failures do not block the workflow (`continue-on-error: true`)
- Verification failures are logged but don't fail the job
- Once proven stable, strict enforcement can be enabled

## Local Signing

For local development or testing:

```bash
# Sign artifacts locally (will prompt for browser authentication)
./scripts/sign-artifacts.sh

# Sign in CI mode (requires OIDC)
./scripts/sign-artifacts.sh --ci

# Sign in warn-only mode
./scripts/sign-artifacts.sh --warn-only
```

Note: Local signing requires browser-based authentication with your identity provider.

## Relationship to Other Security Features

| Feature | Purpose |
|---------|---------|
| SLSA Provenance | Build provenance attestations (what was built, how) |
| Sigstore Signing | Cryptographic signatures (integrity + authenticity) |
| GitHub Attestations | GitHub's attestation storage and verification API |
| SBOM | Software bill of materials (what's in the artifact) |
| Hash Verification | Lockfile integrity (requirements.txt hashes) |

Sigstore signing complements these features by adding cryptographic proof that artifacts haven't been tampered with.

## Troubleshooting

### Signing Fails in CI

1. Check that `id-token: write` permission is set in the workflow
2. Verify the workflow is running on the main repository (not a fork)
3. Check Sigstore service status at https://status.sigstore.dev/

### Verification Fails

1. Ensure you're using the correct bundle file for the artifact
2. Check that the artifact hasn't been modified after signing
3. Verify identity claims match the expected workflow

### "No signature bundle found"

This means the artifact wasn't signed. Check:
1. The signing step completed successfully
2. The artifact was present during signing
3. The signatures artifact was uploaded correctly

### Certificate Expired

Sigstore certificates are short-lived (10 minutes). Verification relies on the Rekor timestamp, not the certificate expiry. If verification fails due to certificate issues:

1. Check the Rekor entry is valid
2. Ensure the bundle contains the full certificate chain
3. Use `--insecure-ignore-sct` flag if SCT verification fails (not recommended for production)

## Related Documentation

- [Sigstore](https://sigstore.dev/)
- [cosign](https://docs.sigstore.dev/cosign/overview/)
- [Fulcio](https://docs.sigstore.dev/fulcio/overview/)
- [Rekor](https://docs.sigstore.dev/rekor/overview/)
- [SLSA Provenance](./SLSA-PROVENANCE.md)
- [SBOM Documentation](./SBOM.md)
- [Security Documentation](./SECURITY.md)
