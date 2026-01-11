#!/usr/bin/env bash
set -euo pipefail

# check-console-log.sh - Check for ungated console.log usage in GUI files
# This script ensures console.log is only used when gated behind a DEBUG flag

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

echo "Checking for ungated console.log in gui/ files..."

# Find all console.log occurrences in gui/ files
# Allowed pattern: "if (DEBUG) console.log" or inside a debugLog wrapper function
# We check for console.log that is NOT preceded by "if (DEBUG)" on the same line

VIOLATIONS=0
TEMP_RESULTS=$(mktemp)
trap "rm -f ${TEMP_RESULTS}" EXIT

# Find all .js files in gui/ and check for ungated console.log
while IFS= read -r file; do
    # Look for console.log that is NOT part of "if (DEBUG) console.log" pattern
    # Allow console.log if it's inside the debugLog wrapper function definition
    if grep -n "console\.log" "$file" | grep -v "if (DEBUG) console\.log" > "${TEMP_RESULTS}"; then
        # We found potential violations, but need to check if they're in the debugLog wrapper
        while IFS=: read -r line_num line_content; do
            # Check if this line is part of the debugLog wrapper definition
            # The pattern we allow: "  if (DEBUG) console.log(...args);" inside debugLog function
            if ! echo "$line_content" | grep -q "if (DEBUG) console\.log"; then
                echo "❌ ${file}:${line_num}: Ungated console.log found"
                echo "   ${line_content}"
                VIOLATIONS=$((VIOLATIONS + 1))
            fi
        done < "${TEMP_RESULTS}"
    fi
done < <(find gui/ -name "*.js" -type f)

if [ ${VIOLATIONS} -gt 0 ]; then
    echo ""
    echo "Found ${VIOLATIONS} ungated console.log statement(s)."
    echo "All console.log usage must be gated behind a DEBUG flag."
    echo "Example: if (DEBUG) console.log(...);"
    exit 1
fi

echo "✓ No ungated console.log found in gui/ files"
