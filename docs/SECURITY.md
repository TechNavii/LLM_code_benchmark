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

## Reporting Security Issues

If you discover a security vulnerability in this project, please report it by:
1. **Do not** open a public GitHub issue
2. Email the maintainers privately
3. Include details about the vulnerability and steps to reproduce

We will respond within 48 hours and work with you to address the issue.
