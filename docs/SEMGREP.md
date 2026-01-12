# Semgrep Security Scanning

This document describes the Semgrep security scanning setup for the benchmark harness.

## Overview

Semgrep is a lightweight SAST (Static Application Security Testing) tool that scans Python and JavaScript code for common security vulnerabilities. The configuration focuses on high-signal security issues without creating excessive noise.

## Running Semgrep

```bash
./scripts/semgrep.sh
```

The script:
- Ensures the virtualenv is set up with semgrep installed
- Scans `server/`, `harness/`, and `gui/` directories
- Excludes `tasks/*` workspaces, `runs/`, `.venv/`, and other generated artifacts
- Uses custom rules defined in `.semgrep.yml`
- Fails on ERROR-level findings, reports WARNING-level findings

## Configuration

The Semgrep ruleset (`.semgrep.yml`) includes checks for:

### Python
- SQL injection (string formatting in SQL queries)
- Hardcoded secrets (password, api_key, token variables)
- Dangerous code execution (`eval()`, `exec()`)
- Unsafe pickle deserialization
- Shell injection via subprocess with `shell=True`
- Weak hash algorithms (MD5, SHA1)

### JavaScript
- Dangerous code execution (`eval()`)
- XSS via `innerHTML` and `document.write`
- Open redirect vulnerabilities

## Suppressions

When a finding is a false positive or acceptable in context, it can be suppressed:

### Inline suppression
Add a `# nosemgrep: rule-id` comment before the line:

```python
# nosemgrep: python-hardcoded-secret
DEFAULT_TIMEOUT = "30s"
```

### File-level documentation
Document suppressions in `.semgrep-suppressions.txt` with:
- File and line number
- Rule ID
- Justification
- Risk assessment

## CI Integration

Semgrep runs on every PR and push via GitHub Actions (`.github/workflows/quality-gates.yml`).

The CI job:
- Installs semgrep from the pinned version in `requirements-dev.txt`
- Runs `./scripts/semgrep.sh`
- Fails the build on ERROR-level findings
- Reports WARNING-level findings without failing

## Adding New Rules

When adding custom rules to `.semgrep.yml`:

1. Test the rule locally first
2. Set appropriate severity (ERROR for critical issues, WARNING for lower severity)
3. Include metadata (category, CWE reference)
4. Ensure the rule has low false-positive rate
5. Document any expected suppressions

## Remediation Workflow

When Semgrep finds an issue:

1. **Verify the finding** - Is it a true positive or false positive?
2. **For true positives**:
   - Fix the vulnerability following secure coding practices
   - Re-run `./scripts/semgrep.sh` to verify the fix
   - Commit the fix
3. **For false positives**:
   - Add inline `# nosemgrep: rule-id` comment with justification
   - Document in `.semgrep-suppressions.txt`
   - Get the suppression reviewed in PR

## Performance

The Semgrep scan is designed to be fast (<10 seconds) to enable frequent local runs and fast CI feedback.

## References

- [Semgrep documentation](https://semgrep.dev/docs/)
- [Semgrep rule registry](https://semgrep.dev/r)
- [CWE (Common Weakness Enumeration)](https://cwe.mitre.org/)
