#!/usr/bin/env bash
# Check that all GitHub Actions in workflow files are pinned to commit SHAs
# Fails if any action uses a version tag (e.g., @v4) instead of a SHA

set -euo pipefail

# Colors for output (disabled if not a terminal)
if [ -t 1 ]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[0;33m'
  NC='\033[0m' # No Color
else
  RED=''
  GREEN=''
  YELLOW=''
  NC=''
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
WORKFLOWS_DIR="$PROJECT_ROOT/.github/workflows"

echo "Checking for unpinned GitHub Actions..."

# Track if we found any issues
FOUND_ISSUES=0
ISSUE_LIST=""

# Pattern to match action uses lines
# Valid: uses: owner/repo@sha  # tag comment (40-char hex SHA)
# Invalid: uses: owner/repo@v1, uses: owner/repo@main, etc.

check_workflow() {
  local file="$1"
  local filename
  filename=$(basename "$file")

  # Extract all 'uses:' lines
  local line_num=0
  while IFS= read -r line; do
    line_num=$((line_num + 1))

    # Skip lines that don't contain 'uses:'
    if ! echo "$line" | grep -q 'uses:'; then
      continue
    fi

    # Extract the action reference (everything after 'uses:')
    local action_ref
    action_ref=$(echo "$line" | sed -n 's/.*uses:[[:space:]]*\([^[:space:]]*\).*/\1/p')

    # Skip if no action reference found
    if [ -z "$action_ref" ]; then
      continue
    fi

    # Skip local actions (starts with ./)
    if [[ "$action_ref" == ./* ]]; then
      continue
    fi

    # Extract the version part (after @)
    local version
    version=$(echo "$action_ref" | sed -n 's/.*@\([^[:space:]]*\).*/\1/p')

    if [ -z "$version" ]; then
      # No version specified at all
      echo -e "${YELLOW}WARNING: $filename:$line_num - No version specified: $action_ref${NC}"
      FOUND_ISSUES=1
      ISSUE_LIST="${ISSUE_LIST}$filename:$line_num: No version - $action_ref\n"
      continue
    fi

    # Check if version is a 40-character hex SHA
    if echo "$version" | grep -qE '^[0-9a-fA-F]{40}$'; then
      # Valid SHA - this is good
      :
    else
      # Not a SHA - could be a tag like v4, main, master, etc.
      echo -e "${RED}UNPINNED: $filename:$line_num - $action_ref${NC}"
      FOUND_ISSUES=1
      ISSUE_LIST="${ISSUE_LIST}$filename:$line_num: Unpinned action - $action_ref\n"
    fi
  done < "$file"
}

# Check all workflow files
if [ -d "$WORKFLOWS_DIR" ]; then
  for workflow in "$WORKFLOWS_DIR"/*.yml "$WORKFLOWS_DIR"/*.yaml; do
    if [ -f "$workflow" ]; then
      check_workflow "$workflow"
    fi
  done
else
  echo -e "${YELLOW}No workflows directory found at $WORKFLOWS_DIR${NC}"
  exit 0
fi

echo ""

if [ "$FOUND_ISSUES" -eq 1 ]; then
  echo -e "${RED}Found unpinned GitHub Actions!${NC}"
  echo ""
  echo "All GitHub Actions should be pinned to immutable commit SHAs to reduce"
  echo "CI supply-chain risk. Version tags like @v4 can be changed by the"
  echo "action maintainer at any time."
  echo ""
  echo "To fix:"
  echo "1. Find the commit SHA for the tag: gh api repos/OWNER/REPO/git/refs/tags/TAG"
  echo "2. Replace @TAG with @SHA and add a comment: uses: owner/repo@SHA  # TAG"
  echo ""
  echo "Example:"
  echo "  Before: uses: actions/checkout@v4"
  echo "  After:  uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4"
  echo ""
  echo "Dependabot can automatically update pinned SHAs. See .github/dependabot.yml."
  exit 1
else
  echo -e "${GREEN}All GitHub Actions are pinned to commit SHAs.${NC}"
  exit 0
fi
