# Security

## Dependency Vulnerability Scanning

This project uses `pip-audit` to scan Python dependencies for known security vulnerabilities.

### Running Security Scans Locally

```bash
./scripts/security-scan.sh
```

This script scans all dependencies in:
- `server/requirements.txt`
- `harness/requirements.txt`
- `requirements-dev.txt`

### Remediation Workflow

When a vulnerability is found:

1. **Review the vulnerability report**
   - Check the severity (HIGH/CRITICAL requires immediate action)
   - Review the CVE/GHSA details and affected versions
   - Determine if the vulnerability affects your use case

2. **Update the affected dependency**
   ```bash
   # Update a specific package
   pip install --upgrade <package-name>

   # Regenerate requirements
   pip freeze > <requirements-file>
   ```

3. **Test the update**
   ```bash
   ./scripts/lint.sh
   ./scripts/typecheck.sh
   ./scripts/test.sh
   ```

4. **If update is not immediately possible**
   - Document why in `.pip-audit-suppressions.txt` with a comment
   - Add the vulnerability ID to the suppressions file
   - Create a tracking issue for future remediation
   - Set a reminder to revisit the issue

### Suppressing Vulnerabilities

Only suppress vulnerabilities when:
- The vulnerability does not apply to your use case
- A fix is not available and the risk is acceptable
- You are waiting for an upstream fix and have documented the issue

To suppress a vulnerability:

1. Add a justification comment to `.pip-audit-suppressions.txt`
2. Add the vulnerability ID on the next line
3. Document in your PR or commit message why the suppression is necessary

Example:
```
# GHSA-xxxx-xxxx-xxxx: Requires admin access which we don't expose in production
GHSA-xxxx-xxxx-xxxx
```

### CI Integration

Security scans run automatically on every PR via GitHub Actions. The build will fail if:
- High or critical vulnerabilities are found
- Vulnerabilities are not properly suppressed with justification

## Dependency Review

This project uses [GitHub Dependency Review](https://github.com/actions/dependency-review-action) to block vulnerable dependency introductions in PRs.

### How It Works

The dependency-review action runs on every PR and:
- Analyzes changes to requirements files (server/, harness/, requirements-dev.txt)
- Detects newly introduced vulnerabilities (high/critical severity)
- Blocks PRs that add vulnerable dependencies
- Ignores tasks/* workspace dependencies (not part of core project)

### Lockfile Support

The action supports our pip-tools lockfile strategy:
- Scans both `.in` source files and `.txt` lock files
- Evaluates changes to locked dependencies
- Respects the pinned versions in our lock files

### Emergency Override Path

In rare cases, you may need to merge a PR that introduces a temporarily vulnerable dependency (e.g., waiting for an upstream fix). Follow this process:

1. **Document the justification**
   - Create a GitHub issue explaining:
     - Why the dependency is needed urgently
     - What vulnerability is being introduced
     - What the mitigation plan is (timeline for fix, workarounds)
     - Who approved the exception

2. **Use repository bypass** (requires admin)
   - A repository admin can merge the PR using "Merge without waiting for requirements"
   - This bypasses the dependency-review check
   - The bypass is logged in the repository audit log

3. **Alternative: Skip the check for this PR**
   - Add a comment to the PR: `@dependabot merge` (if Dependabot PR)
   - Or use the `skip-dependency-review` label (if configured)
   - The label can be added by maintainers with write access

4. **Follow-up required**
   - Create a tracking issue to remediate the vulnerability
   - Set a reminder for 7/14/30 days to check for upstream fixes
   - Update `.pip-audit-suppressions.txt` if the vulnerability persists

### Configuration

The dependency-review action is configured in `.github/workflows/quality-gates.yml`:
- `fail-on-severity: high` - Fails on high and critical vulnerabilities
- `deny-licenses: GPL-3.0, AGPL-3.0` - Blocks problematic licenses
- `allow-unknown-licenses: true` - Allows unknown licenses (brownfield-friendly)
- `allow-paths` - Restricts scanning to core project files (excludes tasks/*)

## Secret Scanning

This project uses [Gitleaks](https://github.com/gitleaks/gitleaks) to scan for accidentally committed secrets and credentials.

### How It Works

Gitleaks scans the git history for:
- API keys and tokens
- Passwords and credentials
- Private keys
- Database connection strings
- OAuth tokens
- Other sensitive information

### CI Integration

Secret scanning runs automatically on:
- Every push to main/master branches
- Every pull request

The build will fail if secrets are detected.

### Handling False Positives

If Gitleaks flags a false positive (e.g., example values, test credentials), add it to `.gitleaks.toml`:

```toml
[allowlist]
paths = [
    '''path/to/file\.txt$''',  # Specific file
]

regexes = [
    '''example_value_pattern''',  # Specific pattern
]
```

### If You Accidentally Commit a Secret

**DO NOT** just delete the secret and commit again. The secret is still in git history.

1. **Immediately rotate the exposed credential**
   - Generate a new key/password/token
   - Update all systems using the old credential
   - Revoke or disable the old credential

2. **Remove the secret from git history**
   ```bash
   # Using git filter-repo (recommended)
   git filter-repo --path path/to/file --invert-paths

   # Or using BFG Repo-Cleaner
   bfg --delete-files path/to/file

   # Force push (coordinate with team first!)
   git push origin --force --all
   ```

3. **Document the incident**
   - Note when it happened
   - What credential was exposed
   - What actions were taken
   - When the credential was rotated

### Best Practices

- **Never commit secrets to version control**
  - Use environment variables (`.env` files are gitignored)
  - Use secret management tools (HashiCorp Vault, AWS Secrets Manager, etc.)
  - Keep `.env.example` updated with variable names (not values)

- **Use the .gitignore**
  - `.env` and similar files are already ignored
  - Add any project-specific secret files to `.gitignore`

- **Review before committing**
  - Check `git diff` before staging
  - Review `git status` before committing
  - Consider using a pre-commit hook (see quality-005-precommit-hooks)

## OSSF Scorecard

This project uses the [OSSF Scorecard](https://securityscorecards.dev/) to analyze repository supply chain security best practices.

### What Is OSSF Scorecard?

OSSF Scorecard is an automated tool from the Open Source Security Foundation that evaluates open source projects against a series of security best practices. It assigns a score (0-10) for each check.

### Checks Performed

The Scorecard analyzes:

| Check | Description |
|-------|-------------|
| Binary-Artifacts | No checked-in binary files |
| Branch-Protection | Branch protection rules on default branch |
| CI-Tests | CI test coverage presence |
| Code-Review | Code review requirements |
| Contributors | Active contributors |
| Dangerous-Workflow | No dangerous workflow patterns (e.g., untrusted inputs in scripts) |
| Dependency-Update-Tool | Automated dependency update tools (e.g., Dependabot) |
| Fuzzing | Fuzz testing presence |
| License | Open source license file |
| Maintained | Active maintenance (commits, releases) |
| Pinned-Dependencies | Pinned dependency versions in workflows |
| Packaging | Published packages |
| SAST | Static analysis tools |
| Security-Policy | SECURITY.md file presence |
| Signed-Releases | Signed releases |
| Token-Permissions | Minimal token permissions in workflows |
| Vulnerabilities | Known vulnerabilities in dependencies |
| Webhooks | Webhook configurations |

### When Scorecard Runs

- **On push to main/master**: Automatically after code changes
- **Weekly (Tuesdays 4AM UTC)**: Scheduled scan for ongoing monitoring
- **Manual trigger**: Via workflow_dispatch for ad-hoc analysis

### Viewing Results

1. **GitHub Security Tab**: SARIF results are uploaded to the repository's Code Scanning alerts
2. **OpenSSF Viewer**: Visit [scorecard.dev](https://scorecard.dev/viewer/?uri=github.com/YOUR_ORG/YOUR_REPO) for a visual dashboard
3. **Workflow Summary**: Each run includes a summary of checks performed
4. **Artifacts**: SARIF results are stored as artifacts for 90 days

### Score Tracking

Scorecard results are tracked over time:
- Each run uploads a SARIF artifact with the commit SHA
- Score history artifacts are retained for 365 days
- Trends can be analyzed by comparing historical artifacts

### Improving Your Score

To improve the Scorecard score:

1. **Branch Protection**: Enable required reviews, status checks, and force-push restrictions
2. **Dependency Updates**: Dependabot is already configured (security-009)
3. **Pinned Actions**: All GitHub Actions are pinned to SHAs (security-011)
4. **Token Permissions**: Workflows use least-privilege permissions (security-010)
5. **SAST**: CodeQL and Bandit are integrated (security-003, security-007)
6. **Security Policy**: This SECURITY.md file satisfies the requirement

### Enforcement Policy

- **Initial (brownfield)**: Warn-only mode - findings are reported but don't fail builds
- **Future**: Once baseline is understood, minimum score thresholds may be enforced

### False Positives

Some checks may not apply to all projects. Known limitations:
- `Signed-Releases`: Not applicable if releases aren't published
- `Packaging`: Not applicable for non-library projects
- `Fuzzing`: May show low score if fuzzing isn't set up (tests-010-harness-patch-parser-fuzz uses Hypothesis, not OSS-Fuzz)

For persistent false positives, document them here and accept the reduced score in those areas.

## Trivy Security Scanning

This project uses [Trivy](https://aquasecurity.github.io/trivy/) for comprehensive security scanning of the repository filesystem and devcontainer.

### What Trivy Scans

Trivy performs multiple types of security analysis:

| Scan Type | Description |
|-----------|-------------|
| Vulnerability | Scans dependencies (Python packages) for known CVEs |
| Misconfiguration | Checks for insecure configuration patterns |
| Secret | Detects accidentally committed secrets and credentials |
| Dockerfile | Analyzes Dockerfile for security best practices |
| Base Image | Scans devcontainer base image for OS package CVEs |

### Running Trivy Locally

```bash
# Run all scans (filesystem + Dockerfile)
./scripts/trivy.sh

# Run filesystem scan only
./scripts/trivy.sh --fs

# Run Dockerfile scan only
./scripts/trivy.sh --dockerfile

# Generate JSON reports
./scripts/trivy.sh --json

# Brownfield mode (warn-only, don't fail)
./scripts/trivy.sh --warn-only
```

### Installation

Trivy must be installed locally to run scans:

```bash
# macOS
brew install trivy

# Linux
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin

# Or use Docker
docker run aquasec/trivy
```

### CI Integration

Trivy runs in the nightly deep scan workflow (`.github/workflows/nightly-deep-scans.yml`):

- **Filesystem scan**: Scans repository for vulnerabilities and misconfigurations
- **Dockerfile config scan**: Checks devcontainer Dockerfile for best practices
- **Base image scan**: Scans the devcontainer base image for OS package CVEs

Results are uploaded as artifacts with 30-day retention.

### Scope and Exclusions

Trivy scans are scoped to match `meta.excludePatterns`:

**Excluded directories:**
- `runs/` - Generated run outputs
- `tasks/` - User task workspaces
- `.venv/` - Virtual environment (managed dependencies)
- `.pytest_cache/`, `__pycache__/` - Cache directories
- `node_modules/` - Node.js dependencies (if any)
- `.git/` - Git internals
- `.benchmarks/`, `.fuzz-reports/`, `.trivy-reports/` - Generated reports

### Suppressing Findings

To suppress known/acceptable findings, add them to `.trivyignore` with explicit justification:

```
# Justification: CVE-XXXX-XXXX affects feature X which we don't use.
# Our code only uses feature Y which is not affected.
# Tracking issue: https://github.com/org/repo/issues/XXX
CVE-XXXX-XXXX
```

**Suppression categories:**

1. **False positives** - Vulnerability does not apply to our usage
2. **Disputed vulnerabilities** - Contested by vendor/community
3. **No fix available** - Risk is mitigated by other controls
4. **Development-only** - Not used in production environments

All suppressions are reviewed and must include justification.

### Enforcement Policy

- **Current (brownfield)**: Warn-only mode in nightly scans
- **Future**: May enforce failure on high/critical findings once baseline is understood

### Relationship to Other Scanners

Trivy complements other security tools in the pipeline:

| Tool | Focus |
|------|-------|
| pip-audit | Python dependency vulnerabilities (PyPI) |
| Trivy | Comprehensive scanning (dependencies, misconfig, secrets, containers) |
| Bandit | Python SAST (code patterns) |
| Semgrep | Multi-language SAST (custom rules) |
| Gitleaks | Git history secret scanning |
| CodeQL | Deep semantic code analysis |

Trivy provides broader coverage (secrets, misconfigurations, container scanning) while pip-audit focuses specifically on Python PyPI vulnerabilities with better accuracy for that narrow scope.

## SLSA Build Provenance

This project generates [SLSA (Supply-chain Levels for Software Artifacts)](https://slsa.dev/) build provenance attestations for critical artifacts.

### What Is SLSA Provenance?

SLSA provenance is a cryptographically signed attestation that describes how software artifacts were built. It enables supply-chain security by providing verifiable evidence of:

- **Source**: Where the artifact came from (repository, commit)
- **Builder**: What system built the artifact (GitHub Actions workflow)
- **Build Process**: How the artifact was created (build steps, inputs)

### Attested Artifacts

The following artifacts receive build provenance attestations:

| Artifact | Description |
|----------|-------------|
| `sbom.json` | Software Bill of Materials (CycloneDX format) |
| `server-requirements.txt` | Server dependency lockfile with hashes |
| `harness-requirements.txt` | Harness dependency lockfile with hashes |
| `requirements-dev.txt` | Dev tools lockfile with hashes |

### Verifying Attestations

```bash
# Verify an artifact using GitHub CLI
gh attestation verify docs/sbom/sbom.json --owner <repo-owner>

# List all attestations for this repository
gh attestation list --owner <repo-owner> --repo <repo-name>
```

### When Attestations Are Generated

- On push to main/master (when lockfiles or SBOM files change)
- Weekly (Mondays 5AM UTC) for freshness
- On manual workflow trigger

### SLSA Level

This implementation achieves **SLSA Level 2**:
- ✅ Provenance exists and is machine-readable (Level 1)
- ✅ Build runs on hosted infrastructure (Level 2)

See [SLSA-PROVENANCE.md](./SLSA-PROVENANCE.md) for full documentation.

## Sigstore Artifact Signing

This project uses [Sigstore](https://sigstore.dev/) for keyless cryptographic signing of critical artifacts (SBOMs and lockfiles).

### What Is Sigstore?

Sigstore provides keyless signing using:
- **Fulcio**: Certificate authority that issues short-lived certificates
- **Rekor**: Transparency log that records all signatures
- **GitHub OIDC**: Identity provider for authentication

### Signed Artifacts

The same artifacts that receive SLSA attestations are also signed with Sigstore:
- `sbom.json` - Software Bill of Materials
- `server-requirements.txt` - Server dependency lockfile
- `harness-requirements.txt` - Harness dependency lockfile
- `requirements-dev.txt` - Dev tools lockfile

### Verifying Signatures

```bash
# Install cosign
brew install cosign  # macOS
# or see https://docs.sigstore.dev/cosign/system_config/installation/

# Verify a signature using bundle
cosign verify-blob \
  --bundle .signatures/sbom.json.bundle \
  --certificate-identity-regexp "https://github.com/OWNER/REPO/.github/workflows/.*" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  docs/sbom/sbom.json

# Use the verification script
./scripts/sign-artifacts.sh --verify
```

### Benefits

- **Integrity**: Proves artifacts haven't been tampered with
- **Authenticity**: Certificates prove artifacts came from this repository
- **Non-repudiation**: Rekor log provides immutable evidence of signing
- **No key management**: Keyless signing eliminates private key risks

See [SIGSTORE.md](./SIGSTORE.md) for full documentation.

## Reporting Security Issues

If you discover a security vulnerability in this project, please report it by:
1. **Do not** open a public GitHub issue
2. Email the maintainers privately
3. Include details about the vulnerability and steps to reproduce

We will respond within 48 hours and work with you to address the issue.
