# Branch Protection Requirements

This document defines the branch protection configuration for the `main` branch
to ensure code quality, security, and a consistent merge process.

## Required Status Checks

The following status checks must pass before merging to `main`:

### Critical (must pass)

| Check Name | Workflow | Description |
|------------|----------|-------------|
| `quality-checks (ubuntu-latest, 3.11)` | quality-gates.yml | Lint, typecheck, tests, security scans on Ubuntu/Python 3.11 |
| `quality-checks (ubuntu-latest, 3.12)` | quality-gates.yml | Lint, typecheck, tests, security scans on Ubuntu/Python 3.12 |
| `quality-checks (macos-latest, 3.11)` | quality-gates.yml | Cross-platform validation on macOS/Python 3.11 |
| `quality-checks (macos-latest, 3.12)` | quality-gates.yml | Cross-platform validation on macOS/Python 3.12 |
| `dependency-review` | quality-gates.yml | Blocks PRs introducing high/critical vulnerabilities |
| `gitleaks` | secret-scanning.yml | Prevents accidental credential commits |

### Recommended (should pass)

| Check Name | Workflow | Description |
|------------|----------|-------------|
| `Analyze (python)` | codeql.yml | Python SAST analysis |
| `Analyze (javascript)` | codeql.yml | JavaScript SAST analysis |
| `ossf-scorecard` | ossf-scorecard.yml | Supply chain best practices |

## Review Requirements

- **Required approving reviews**: 1 (minimum)
- **Dismiss stale pull request approvals**: Yes (when new commits are pushed)
- **Require review from code owners**: Optional (if CODEOWNERS file exists)
- **Restrict who can dismiss reviews**: Maintainers only

## Merge Strategy

- **Require linear history**: Recommended (forces squash or rebase)
- **Allow squash merging**: Yes (preferred for feature branches)
- **Allow merge commits**: Yes (for release branches if needed)
- **Allow rebase merging**: Yes (for clean history)
- **Delete head branches after merge**: Recommended

## Repository Settings

### Protected Branches

For the `main` branch:

- **Require a pull request before merging**: Yes
- **Require status checks to pass**: Yes
- **Require branches to be up to date**: Recommended
- **Do not allow bypassing the above settings**: Yes (for non-admins)
- **Restrict pushes**: Only maintainers (no force push)
- **Allow force pushes**: No
- **Allow deletions**: No

### Signed Commits (Optional)

- **Require signed commits**: Optional but recommended
- Supports GPG or SSH commit signing

## Emergency Override Procedure

In critical situations where immediate changes are needed:

### Criteria for Emergency Override

1. **Production outage** - Service is down and a hotfix is required
2. **Security incident** - Active vulnerability being exploited
3. **Data loss prevention** - Imminent risk of data corruption

### Override Process

1. **Document the emergency** - Create an issue with label `emergency`
2. **Notify team leads** - Contact repository maintainers
3. **Admin bypass** - Repository admin can merge without checks
4. **Post-merge review** - Within 24 hours, submit a retrospective:
   - What was the emergency?
   - Why couldn't normal process be followed?
   - What tests/checks were skipped?
   - Follow-up actions to prevent recurrence

### Follow-up Requirements

After an emergency merge:

1. Create a PR with proper tests for the hotfix
2. Ensure all skipped checks pass on the follow-up PR
3. Document lessons learned in the issue
4. Consider adding automated checks to prevent similar emergencies

## Verification Script

A script is provided to verify branch protection settings:

```bash
./scripts/check-branch-protection.sh
```

This script uses the GitHub API to check if branch protection rules match
the requirements documented above. It requires:
- `GITHUB_TOKEN` environment variable with `repo` scope
- Repository owner/name detection from git remote

## Configuration via GitHub Settings

To configure branch protection manually:

1. Go to **Settings** > **Branches**
2. Click **Add branch protection rule**
3. Set **Branch name pattern**: `main`
4. Enable the settings as documented above
5. Click **Create** or **Save changes**

## GitHub CLI Quick Setup

```bash
# Enable branch protection with required checks
gh api repos/{owner}/{repo}/branches/main/protection \
  -X PUT \
  -F required_status_checks='{"strict":true,"contexts":["quality-checks (ubuntu-latest, 3.11)","quality-checks (ubuntu-latest, 3.12)","quality-checks (macos-latest, 3.11)","quality-checks (macos-latest, 3.12)","dependency-review","gitleaks"]}' \
  -F enforce_admins=false \
  -F required_pull_request_reviews='{"dismiss_stale_reviews":true,"require_code_owner_reviews":false,"required_approving_review_count":1}' \
  -F restrictions=null \
  -F allow_force_pushes=false \
  -F allow_deletions=false
```

## Related Documentation

- [GitHub Branch Protection Rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [Required Status Checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-status-checks-before-merging)
- [CODEOWNERS File](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
