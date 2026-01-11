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

## Secret Scanning

(To be added in security-002-secret-scanning)

## Reporting Security Issues

If you discover a security vulnerability in this project, please report it by:
1. **Do not** open a public GitHub issue
2. Email the maintainers privately
3. Include details about the vulnerability and steps to reproduce

We will respond within 48 hours and work with you to address the issue.
