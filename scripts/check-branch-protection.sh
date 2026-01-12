#!/usr/bin/env bash
# Check branch protection settings against documented requirements
#
# This script verifies that the main branch has proper protection rules
# configured as documented in docs/BRANCH_PROTECTION.md
#
# Requirements:
# - GITHUB_TOKEN environment variable with 'repo' scope
# - gh CLI (optional, falls back to curl)
# - jq for JSON parsing
#
# Usage:
#   ./scripts/check-branch-protection.sh [branch]
#
# Arguments:
#   branch    Branch to check (default: main)
#
# Exit codes:
#   0 - All checks passed
#   1 - Branch protection misconfigured
#   2 - Unable to fetch protection settings (permissions/API error)

set -euo pipefail

# Configuration
BRANCH="${1:-main}"
WARN_ONLY="${WARN_ONLY:-false}"

# Required status checks (from docs/BRANCH_PROTECTION.md)
REQUIRED_CHECKS=(
    "quality-checks (ubuntu-latest, 3.11)"
    "quality-checks (ubuntu-latest, 3.12)"
    "quality-checks (macos-latest, 3.11)"
    "quality-checks (macos-latest, 3.12)"
    "dependency-review"
    "gitleaks"
)

# Color output helpers
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

log_pass() { echo -e "${GREEN}✓${NC} $1"; }
log_fail() { echo -e "${RED}✗${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_info() { echo -e "  $1"; }

# Detect repository from git remote
detect_repo() {
    local remote_url
    remote_url=$(git remote get-url origin 2>/dev/null || echo "")

    if [[ -z "$remote_url" ]]; then
        echo "Error: Unable to detect repository from git remote" >&2
        return 1
    fi

    # Extract owner/repo from various URL formats
    # SSH: git@github.com:owner/repo.git
    # HTTPS: https://github.com/owner/repo.git
    local repo
    repo=$(echo "$remote_url" | sed -E 's#.*github\.com[:/]([^/]+/[^/]+?)(\.git)?$#\1#')

    if [[ -z "$repo" || "$repo" == "$remote_url" ]]; then
        echo "Error: Unable to parse repository from remote URL: $remote_url" >&2
        return 1
    fi

    echo "$repo"
}

# Fetch branch protection settings
fetch_protection() {
    local repo="$1"
    local branch="$2"

    # Try gh CLI first
    if command -v gh &>/dev/null; then
        gh api "repos/${repo}/branches/${branch}/protection" 2>/dev/null && return 0
    fi

    # Fall back to curl with GITHUB_TOKEN
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        curl -sS -H "Authorization: token ${GITHUB_TOKEN}" \
             -H "Accept: application/vnd.github+json" \
             "https://api.github.com/repos/${repo}/branches/${branch}/protection" 2>/dev/null && return 0
    fi

    return 1
}

# Main verification logic
main() {
    echo "Branch Protection Verification"
    echo "=============================="
    echo ""

    # Detect repository
    local repo
    if ! repo=$(detect_repo); then
        echo "Unable to detect repository. Please run from a git repository." >&2
        exit 2
    fi
    echo "Repository: $repo"
    echo "Branch: $BRANCH"
    echo ""

    # Fetch protection settings
    local protection
    if ! protection=$(fetch_protection "$repo" "$BRANCH" 2>&1); then
        # Check if it's a 404 (no protection) or permission error
        if echo "$protection" | grep -q "Not Found\|404"; then
            log_fail "Branch protection is NOT enabled on '$BRANCH'"
            echo ""
            echo "To enable branch protection, see: docs/BRANCH_PROTECTION.md"
            [[ "$WARN_ONLY" == "true" ]] && exit 0
            exit 1
        else
            log_warn "Unable to fetch branch protection settings"
            log_info "This may be due to missing GITHUB_TOKEN or insufficient permissions"
            log_info "Required scope: 'repo' for private repos, 'public_repo' for public"
            echo ""
            echo "To authenticate:"
            echo "  export GITHUB_TOKEN=ghp_your_token_here"
            echo "  # or"
            echo "  gh auth login"
            exit 2
        fi
    fi

    # Parse protection settings
    local exit_code=0

    echo "Checking required settings..."
    echo ""

    # Check: Require pull request reviews
    local require_reviews
    require_reviews=$(echo "$protection" | jq -r '.required_pull_request_reviews != null')
    if [[ "$require_reviews" == "true" ]]; then
        log_pass "Pull request reviews required"

        # Check dismiss stale reviews
        local dismiss_stale
        dismiss_stale=$(echo "$protection" | jq -r '.required_pull_request_reviews.dismiss_stale_reviews // false')
        if [[ "$dismiss_stale" == "true" ]]; then
            log_pass "  Stale reviews are dismissed on new commits"
        else
            log_warn "  Stale reviews NOT dismissed (recommended)"
        fi

        # Check required reviewers
        local review_count
        review_count=$(echo "$protection" | jq -r '.required_pull_request_reviews.required_approving_review_count // 0')
        if [[ "$review_count" -ge 1 ]]; then
            log_pass "  Required approving reviews: $review_count"
        else
            log_fail "  Required approving reviews: $review_count (should be ≥1)"
            exit_code=1
        fi
    else
        log_fail "Pull request reviews NOT required"
        exit_code=1
    fi

    echo ""

    # Check: Require status checks
    local require_status
    require_status=$(echo "$protection" | jq -r '.required_status_checks != null')
    if [[ "$require_status" == "true" ]]; then
        log_pass "Status checks required"

        # Check strict mode (up-to-date branches)
        local strict
        strict=$(echo "$protection" | jq -r '.required_status_checks.strict // false')
        if [[ "$strict" == "true" ]]; then
            log_pass "  Require branches to be up-to-date: enabled"
        else
            log_warn "  Require branches to be up-to-date: disabled (recommended)"
        fi

        # Check required contexts
        local contexts
        contexts=$(echo "$protection" | jq -r '.required_status_checks.contexts[]? // empty' 2>/dev/null || echo "")

        echo ""
        echo "  Checking required status checks..."
        for check in "${REQUIRED_CHECKS[@]}"; do
            if echo "$contexts" | grep -qF "$check"; then
                log_pass "    $check"
            else
                log_fail "    $check (missing)"
                exit_code=1
            fi
        done
    else
        log_fail "Status checks NOT required"
        exit_code=1
    fi

    echo ""

    # Check: Force push disabled
    local allow_force
    allow_force=$(echo "$protection" | jq -r '.allow_force_pushes.enabled // false')
    if [[ "$allow_force" == "false" ]]; then
        log_pass "Force push disabled"
    else
        log_fail "Force push is ALLOWED (should be disabled)"
        exit_code=1
    fi

    # Check: Branch deletion disabled
    local allow_delete
    allow_delete=$(echo "$protection" | jq -r '.allow_deletions.enabled // false')
    if [[ "$allow_delete" == "false" ]]; then
        log_pass "Branch deletion disabled"
    else
        log_warn "Branch deletion is ALLOWED"
    fi

    echo ""

    # Summary
    if [[ $exit_code -eq 0 ]]; then
        echo -e "${GREEN}All branch protection checks passed!${NC}"
    else
        echo -e "${RED}Some branch protection checks failed.${NC}"
        echo "See docs/BRANCH_PROTECTION.md for configuration guidance."

        if [[ "$WARN_ONLY" == "true" ]]; then
            echo ""
            log_warn "WARN_ONLY=true: Exiting with success despite failures"
            exit 0
        fi
    fi

    exit $exit_code
}

main "$@"
