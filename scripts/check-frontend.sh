#!/usr/bin/env bash
set -euo pipefail

# check-frontend.sh - Minimal frontend quality checks for gui/ (JS/CSS)
# This script performs lightweight linting without requiring Node.js/npm

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

echo "Running frontend quality checks on gui/..."

VIOLATIONS=0

# Check 1: Detect trailing whitespace in JS/CSS files (warning only for brownfield)
echo "  Checking for trailing whitespace..."
TRAILING_WS_COUNT=$(
    { grep -r '[[:space:]]$' gui/ --include="*.js" --include="*.css" --exclude-dir=node_modules 2>/dev/null || true; } \
        | wc -l \
        | tr -d ' '
)
if [ "$TRAILING_WS_COUNT" -gt 0 ]; then
    echo "⚠️  Found ${TRAILING_WS_COUNT} lines with trailing whitespace (warning only)"
fi

# Check 2: Detect common syntax errors - unclosed braces
echo "  Checking for balanced braces..."
for file in $(find gui/ -name "*.js" -o -name "*.css" | grep -v node_modules); do
    # Count opening and closing braces
    open_braces=$(grep -o '{' "$file" | wc -l | tr -d ' ')
    close_braces=$(grep -o '}' "$file" | wc -l | tr -d ' ')

    if [ "$open_braces" -ne "$close_braces" ]; then
        echo "❌ ${file}: Unbalanced braces (open: ${open_braces}, close: ${close_braces})"
        VIOLATIONS=$((VIOLATIONS + 1))
    fi
done

# Check 3: Detect var usage (prefer const/let)
echo "  Checking for 'var' usage (prefer const/let)..."
if grep -rn '\bvar\s' gui/ --include="*.js" --exclude-dir=node_modules 2>/dev/null | grep -v '//.*var\s'; then
    echo "⚠️  Found 'var' usage (prefer const/let)"
    # Note: This is a warning, not a hard failure for brownfield code
fi

# Check 4: Detect debugger statements
echo "  Checking for debugger statements..."
if grep -rn '\bdebugger\b' gui/ --include="*.js" --exclude-dir=node_modules 2>/dev/null; then
    echo "❌ Found debugger statement(s)"
    VIOLATIONS=$((VIOLATIONS + 1))
fi

# Check 5: Detect common CSS issues - empty rulesets
# Use awk for cross-platform compatibility (grep -P not available on macOS)
echo "  Checking for empty CSS rulesets..."
EMPTY_RULESETS=$(find gui/ -name "*.css" -exec awk '/\{[[:space:]]*\}/' {} + 2>/dev/null | wc -l | tr -d ' ')
if [ "$EMPTY_RULESETS" -gt 0 ]; then
    echo "⚠️  Found empty CSS rulesets"
    # Note: Warning only for brownfield code
fi

if [ ${VIOLATIONS} -gt 0 ]; then
    echo ""
    echo "Found ${VIOLATIONS} frontend quality issue(s)."
    exit 1
fi

echo "✓ Frontend quality checks passed"
