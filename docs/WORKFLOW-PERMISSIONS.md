# GitHub Actions Workflow Permissions

This document describes the permission model for GitHub Actions workflows in this repository and provides a checklist for periodic security reviews.

## Permission Principles

1. **Least Privilege**: All workflows use the minimum permissions required for their tasks
2. **Explicit Declarations**: All workflows declare permissions explicitly (no implicit defaults)
3. **No Long-Lived Secrets**: Workflows use short-lived GITHUB_TOKEN instead of PATs where possible
4. **PR Context Restriction**: Write permissions are restricted to PR contexts where applicable
5. **Fork PR Hardening**: Fork PRs are treated with reduced trust (see below)

## Workflow Permission Summary

| Workflow | contents | pull-requests | checks | security-events | actions | issues |
|----------|----------|---------------|--------|-----------------|---------|--------|
| quality-gates.yml | read | write | write | - | - | - |
| secret-scanning.yml | read | - | - | - | - | - |
| nightly-deep-scans.yml | read | - | - | - | - | - |
| codeql.yml | read | - | - | write | read | - |

### Permission Justifications

#### quality-gates.yml
- `contents: read` - Checkout code, read repository files
- `pull-requests: write` - Post diff-coverage comments, dependency-review comments
- `checks: write` - Publish test results annotations via EnricoMi/publish-unit-test-result-action

#### secret-scanning.yml
- `contents: read` - Checkout code for Gitleaks scanning (no write needed)

#### nightly-deep-scans.yml
- `contents: read` - Checkout code for security scans
- Note: If issue creation for critical findings is enabled, `issues: write` should be added

#### codeql.yml
- `contents: read` - Checkout code for analysis
- `security-events: write` - Upload SARIF results to Security tab
- `actions: read` - Required by CodeQL action

## Periodic Review Checklist

Review these items quarterly (or after significant workflow changes):

### Permissions Audit
- [ ] All workflows declare explicit `permissions:` blocks
- [ ] No workflows use `permissions: write-all` or omit permissions (implicit write)
- [ ] `pull-requests: write` is only used where PR comments are needed
- [ ] `contents: write` is not used unless absolutely necessary
- [ ] `security-events: write` is only used by security-focused workflows

### Token Usage Audit
- [ ] `GITHUB_TOKEN` is used instead of PATs where possible
- [ ] No long-lived secrets are stored in repository secrets unnecessarily
- [ ] Secrets are scoped to specific environments if applicable

### Action Version Audit
- [ ] All third-party actions are pinned to commit SHAs (40-char hex)
- [ ] Version tags are documented in comments (e.g., `@abc123  # v4`)
- [ ] `./scripts/check-pinned-actions.sh` passes with no findings
- [ ] Dependabot is configured to update action SHAs
- [ ] Actions from untrusted sources are avoided or audited

### Context Restrictions
- [ ] PR comment actions are gated with `if: github.event_name == 'pull_request'`
- [ ] Push-triggered workflows don't have unnecessary write permissions
- [ ] Scheduled workflows have minimal permissions

### Fork PR Hardening
- [ ] `pull_request_target` is NOT used (allows fork PRs with elevated permissions)
- [ ] Fork PR detection: `github.event.pull_request.head.repo.full_name != github.repository`
- [ ] Write permissions steps skip for fork PRs via `IS_FORK_PR` environment variable
- [ ] Cache writes are disabled for fork PRs (use `actions/cache/restore` only)
- [ ] PR comments/annotations skip for fork PRs

## Adding New Workflows

When creating new workflows:

1. Start with `permissions: {}` (no permissions) and add only what's needed
2. Document why each permission is required
3. Prefer read permissions over write permissions
4. Use job-level permissions if different jobs need different access
5. Test with restricted permissions before expanding

## GitHub Actions SHA Pinning

All GitHub Actions in this repository must be pinned to immutable commit SHAs to reduce supply-chain risk. Version tags like `@v4` can be changed by the action maintainer at any time, potentially introducing malicious code. SHA pinning ensures you're always running exactly the code you reviewed.

### Format

```yaml
# Correct: SHA-pinned with version comment
uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4

# Incorrect: version tag (mutable)
uses: actions/checkout@v4
```

### How to Pin an Action

1. Find the commit SHA for the desired version:
   ```bash
   gh api repos/OWNER/REPO/git/refs/tags/TAG --jq '.object.sha'
   ```

2. If the result is a tag object (not a commit), dereference it:
   ```bash
   gh api repos/OWNER/REPO/git/tags/TAG_SHA --jq '.object.sha'
   ```

3. Update the workflow with the SHA and add a version comment

### Keeping SHAs Updated

Dependabot is configured to automatically update SHA-pinned actions when new versions are released. It will:
- Detect that actions are pinned to SHAs
- Find new releases and their corresponding SHAs
- Create PRs to update to the new SHAs

See `.github/dependabot.yml` for the update schedule (weekly on Mondays).

### CI Enforcement

The `./scripts/check-pinned-actions.sh` script runs in CI and fails if any action uses a version tag instead of a SHA. This prevents accidental introduction of unpinned actions.

### Exceptions

Exceptions to SHA pinning require explicit justification and should be documented. Currently, no exceptions are allowed.

## Fork PR Hardening

Pull requests from forks require special handling to prevent security risks:

### Threat Model

Fork PRs can be used to:
1. **Steal secrets**: Malicious code in PRs accessing `secrets.*`
2. **Cache poisoning**: Writing malicious data to shared caches
3. **Supply chain attacks**: Modifying workflow files to gain elevated access
4. **Resource abuse**: Triggering expensive scans/builds

### Protections Implemented

#### 1. Avoid `pull_request_target`
We use `pull_request` instead of `pull_request_target`. The latter runs with elevated permissions from the base branch, which can be exploited by malicious fork PRs.

#### 2. Fork Detection
Workflows detect fork PRs using:
```yaml
env:
  IS_FORK_PR: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name != github.repository }}
```

#### 3. Conditional Permissions
Steps requiring write permissions skip for fork PRs:
- **PR Comments**: Diff coverage, dependency review comments
- **Check Annotations**: Test result annotations
- **Cache Writes**: Virtualenv cache saves

```yaml
# Example: Skip PR comments for forks
- name: Post comment
  if: env.IS_FORK_PR != 'true'
  uses: actions/github-script@...
```

#### 4. Cache Poisoning Prevention
Fork PRs use restore-only caching:
```yaml
# Restore-only for forks (no writes)
- name: Cache virtualenv (restore-only for forks)
  if: env.IS_FORK_PR == 'true'
  uses: actions/cache/restore@...
```

Same-repo PRs and pushes get full cache read/write access.

#### 5. Sensitive Workflows Exclude PRs
Some workflows run only on push/schedule, never on PRs:
- **ossf-scorecard.yml**: Runs on push to main only
- **nightly-deep-scans.yml**: Runs on schedule/manual dispatch only

### What Fork PRs Still Get

Fork PRs still receive:
- ✅ Full lint, typecheck, and test validation
- ✅ Security scans (Bandit, Semgrep, pip-audit)
- ✅ OpenAPI validation
- ✅ JUnit/coverage XML artifacts (uploaded, not annotated)
- ✅ SBOM generation

Fork PRs do NOT get:
- ❌ PR comments (diff coverage, dependency review)
- ❌ Test result annotations
- ❌ Cache writes (prevents poisoning)
- ❌ OSSF Scorecard (requires id-token:write)

### Adding New Workflows

When adding workflows that handle PRs:
1. Detect fork PRs with `IS_FORK_PR` environment variable
2. Skip write-permission steps for forks
3. Use `actions/cache/restore` instead of `actions/cache` for forks
4. Avoid `pull_request_target` unless absolutely necessary (and well-audited)
5. Document any exceptions with explicit justification

## Security Best Practices

1. **Never** store actual secrets in workflow files
2. **Never** echo secrets or tokens to logs
3. **Always** use `${{ secrets.* }}` for sensitive values
4. **Prefer** OIDC authentication over long-lived tokens (for cloud providers)
5. **Review** third-party actions before adding them

## Related Documentation

- [GitHub Actions Security Hardening](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions)
- [GitHub Token Permissions](https://docs.github.com/en/actions/security-guides/automatic-token-authentication)
- [SECURITY.md](./SECURITY.md) - Security policies for this repository
