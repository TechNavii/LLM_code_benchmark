#!/usr/bin/env bash
set -euo pipefail

# check-artifact-hygiene.sh - Verify no generated artifacts are accidentally tracked in git
#
# This script fails if any files under artifact/cache directories are tracked in git.
# It helps prevent accidental commits of:
# - Python caches (.pytest_cache/, .mypy_cache/, .ruff_cache/, __pycache__/)
# - Coverage artifacts (htmlcov/, .coverage*, coverage.xml, junit.xml)
# - Hypothesis test data (.hypothesis/)
# - Virtual environments (.venv/, venv/, env/)
# - Build artifacts (dist/, build/, *.egg-info/)
# - IDE caches (.idea/, .vscode/)
# - Node modules (node_modules/)
# - SBOM and security reports (docs/sbom/, .trivy-reports/, .signatures/)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

echo "Checking for accidentally tracked artifact files..."
echo "======================================================"
echo ""

# Artifact directories that should never have tracked files
ARTIFACT_DIRS=(
    ".pytest_cache"
    ".mypy_cache"
    ".ruff_cache"
    ".hypothesis"
    "__pycache__"
    "htmlcov"
    ".venv"
    "venv"
    "env"
    "node_modules"
    ".idea"
    ".vscode"
    "dist"
    "build"
    ".gocache"
    "target"
    "docs/sbom"
    ".trivy-reports"
    ".signatures"
    ".benchmarks"
    ".fuzz-reports"
    "runs"
)

# Artifact file patterns that should never be tracked
ARTIFACT_FILES=(
    "*.pyc"
    "*.pyo"
    "*.pyd"
    ".coverage"
    ".coverage.*"
    "coverage.xml"
    "junit.xml"
    "*.egg-info"
    ".DS_Store"
)

found_issues=0
issues=""

# Helper function to indent multiline text
indent_lines() {
    while IFS= read -r line; do
        printf '  %s\n' "$line"
    done
}

# Check for tracked files in artifact directories
for dir in "${ARTIFACT_DIRS[@]}"; do
    # Find any tracked files under this directory
    tracked=$(git ls-files --cached "${dir}/" 2>/dev/null | head -10 || true)
    if [[ -n "$tracked" ]]; then
        issues+="ERROR: Found tracked files in ${dir}/:\n"
        issues+="$(echo "$tracked" | indent_lines)\n"
        issues+="\n"
        found_issues=1
    fi
done

# Check for tracked artifact files at any level
for pattern in "${ARTIFACT_FILES[@]}"; do
    # Use git ls-files with glob pattern
    tracked=$(git ls-files --cached "${pattern}" 2>/dev/null | head -10 || true)
    if [[ -n "$tracked" ]]; then
        issues+="ERROR: Found tracked artifact files matching ${pattern}:\n"
        issues+="$(echo "$tracked" | indent_lines)\n"
        issues+="\n"
        found_issues=1
    fi
done

# Check for coverage files with spaces (e.g., ".coverage 2")
tracked_coverage=$(git ls-files --cached | grep -E '^\.coverage' | head -10 || true)
if [[ -n "$tracked_coverage" ]]; then
    issues+="ERROR: Found tracked coverage files:\n"
    issues+="$(echo "$tracked_coverage" | indent_lines)\n"
    issues+="\n"
    found_issues=1
fi

# Check for any __pycache__ directories (can be nested)
tracked_pycache=$(git ls-files --cached | grep '__pycache__' | head -10 || true)
if [[ -n "$tracked_pycache" ]]; then
    issues+="ERROR: Found tracked __pycache__ files:\n"
    issues+="$(echo "$tracked_pycache" | indent_lines)\n"
    issues+="\n"
    found_issues=1
fi

if [[ $found_issues -eq 1 ]]; then
    echo "FAILED: Artifact files are tracked in git!"
    echo ""
    echo -e "$issues"
    echo "To fix:"
    echo "  1. Add the files to .gitignore"
    echo "  2. Remove from git tracking: git rm --cached <file>"
    echo "  3. Commit the changes"
    echo ""
    echo "If a file must be tracked, add it to .artifact-hygiene-allowlist.txt with justification."
    exit 1
fi

# Verify .gitignore covers all artifact directories
echo "Verifying .gitignore coverage..."
missing_ignores=()

for dir in "${ARTIFACT_DIRS[@]}"; do
    # Create a test file path
    test_path="${dir}/test_file"
    if ! git check-ignore -q "$test_path" 2>/dev/null; then
        missing_ignores+=("$dir/")
    fi
done

if [[ ${#missing_ignores[@]} -gt 0 ]]; then
    echo ""
    echo "WARNING: The following directories are not in .gitignore:"
    for dir in "${missing_ignores[@]}"; do
        echo "  - $dir"
    done
    echo ""
    echo "Consider adding them to prevent accidental commits."
fi

echo ""
echo "No artifact files are tracked in git."
echo ""
echo "check-artifact-hygiene passed"
