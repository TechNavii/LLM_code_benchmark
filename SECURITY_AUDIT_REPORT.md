# Security Audit Report: Exposed Secrets and Privacy Issues

**Date:** 2026-01-16
**Repository:** LLM_code_benchmark
**Branches Audited:** main, GUI, enhancement-plan, feature/lmstudio-support, add-claude-github-actions-1767012647259

---

## Executive Summary

This audit identified **1 critical finding** related to an exposed secret in the git history. The current codebase follows good security practices, but remediation is required for the historical exposure.

---

## Critical Findings

### 1. Exposed WebUI Secret Key in Git History

**Severity:** CRITICAL
**Status:** Secret removed from current code, but still accessible in git history

**Details:**
- **File:** `scripts/.webui_secret_key`
- **Exposed Secret:** `FLWCQ912doHxLn8v`
- **Added in commit:** `c703ab2` ("Added Fix" - Dec 7, 2025)
- **Removed in commit:** `8e5bb4c` ("Remove unused webui secret key file" - Dec 7, 2025)
- **Affected Branches:** main, GUI, add-claude-github-actions-1767012647259, claude/audit-exposed-secrets-i6SSQ

**Risk:**
Anyone with access to this repository can retrieve this secret from the git history using:
```bash
git show c703ab2:scripts/.webui_secret_key
```

**Remediation Required:**
1. **Immediate:** Rotate/invalidate this secret if it's still in use anywhere
2. **Git History Cleanup:** Use `git filter-branch` or BFG Repo-Cleaner to remove the secret from history
3. **Force Push:** After cleanup, force push to all affected branches

---

## Positive Security Practices Observed

### 1. Environment Variable Configuration
- API keys are loaded from environment variables, not hardcoded
- `.env` files are properly gitignored
- `.env.example` contains only placeholder values (`replace-with-your-key`)

### 2. Gitignore Configuration
The `.gitignore` properly excludes:
- `.env` and `.env.*` files
- Database files (`*.db`, `*.sqlite`)
- IDE configurations
- Build artifacts

### 3. Log Redaction
The codebase includes comprehensive log redaction tests (`tests/test_log_redaction.py`) that verify sensitive data is properly redacted before logging.

### 4. Configuration Management
- `harness/config.py` and `server/config.py` use Pydantic settings with proper environment variable loading
- No hardcoded secrets in configuration files

---

## Items Reviewed (No Issues Found)

| Check | Result |
|-------|--------|
| OpenAI API keys (sk-*) | Only test data in test files |
| GitHub tokens (ghp_*, gho_*) | None found |
| AWS credentials (AKIA*) | Only in scanner scripts (checking for them) |
| Slack tokens (xox*) | None found |
| Private keys (PEM/RSA) | None found |
| Database connection strings | None found |
| .env files committed | None found |

---

## Recommendations

### Immediate Actions
1. **Rotate the exposed secret** `FLWCQ912doHxLn8v` if it's used anywhere
2. **Clean git history** to remove the secret permanently:
   ```bash
   # Using BFG Repo-Cleaner (recommended)
   bfg --delete-files .webui_secret_key
   git reflog expire --expire=now --all && git gc --prune=now --aggressive
   git push --force --all
   ```

### Long-term Improvements
1. **Pre-commit hooks:** Add a pre-commit hook to scan for secrets before commits
2. **CI/CD scanning:** Implement secret scanning in CI pipeline (e.g., truffleHog, git-secrets)
3. **Branch protection:** Enable branch protection rules to require secret scanning checks

---

## Audit Methodology

1. Searched all branches for common secret patterns (API keys, tokens, passwords)
2. Reviewed configuration files and environment examples
3. Searched git history for deleted sensitive files
4. Checked for accidentally committed .env or credential files
5. Verified gitignore rules for sensitive file types

---

## Appendix: Files Containing Test Secrets (Expected)

The following files contain test/mock secrets for testing log redaction functionality. These are **not** security issues:

- `tests/test_log_redaction.py` - Contains mock API keys for testing redaction
- `conftest.py` - Sets dummy test API key (`test-openrouter-api-key-1234567890`)
- `tests/test_harness_server_e2e.py` - Uses dummy key for E2E tests
