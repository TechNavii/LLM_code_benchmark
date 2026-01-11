# GitHub Actions Workflow Permissions

This document describes the permission model for GitHub Actions workflows in this repository and provides a checklist for periodic security reviews.

## Permission Principles

1. **Least Privilege**: All workflows use the minimum permissions required for their tasks
2. **Explicit Declarations**: All workflows declare permissions explicitly (no implicit defaults)
3. **No Long-Lived Secrets**: Workflows use short-lived GITHUB_TOKEN instead of PATs where possible
4. **PR Context Restriction**: Write permissions are restricted to PR contexts where applicable

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
- [ ] All third-party actions use pinned versions (SHA or tag)
- [ ] Dependabot is configured to update action versions
- [ ] Actions from untrusted sources are avoided or audited

### Context Restrictions
- [ ] PR comment actions are gated with `if: github.event_name == 'pull_request'`
- [ ] Push-triggered workflows don't have unnecessary write permissions
- [ ] Scheduled workflows have minimal permissions

## Adding New Workflows

When creating new workflows:

1. Start with `permissions: {}` (no permissions) and add only what's needed
2. Document why each permission is required
3. Prefer read permissions over write permissions
4. Use job-level permissions if different jobs need different access
5. Test with restricted permissions before expanding

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
