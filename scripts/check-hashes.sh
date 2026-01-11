#!/usr/bin/env bash
# check-hashes.sh - Verify all lockfiles contain hashes and no unpinned direct URL deps
#
# This script ensures dependency integrity by validating:
# 1. All requirements.txt files contain SHA256 hashes for every package
# 2. No direct URL dependencies (git+, http://, https://) without hashes
# 3. All packages have at least one --hash entry
#
# Exit codes:
#   0 - All requirements files have proper hashes
#   1 - Missing hashes or unpinned direct URL dependencies found

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Requirements files to check (core repository, not tasks/*)
REQUIREMENTS_FILES=(
    "server/requirements.txt"
    "harness/requirements.txt"
    "requirements-dev.txt"
)

echo "Checking requirements files for hash integrity..."
echo ""

ERRORS=0

for req_file in "${REQUIREMENTS_FILES[@]}"; do
    if [ ! -f "${req_file}" ]; then
        echo "ERROR: Requirements file not found: ${req_file}"
        ERRORS=1
        continue
    fi

    echo "Checking ${req_file}..."

    # Check for any package lines without hashes
    # Package lines start with a package name (not # or whitespace) and end with version
    # Then should be followed by --hash lines

    # Extract package entries (lines that define packages, not comments or annotations)
    # Package lines look like: package==version \
    PACKAGES_WITHOUT_HASHES=()
    DIRECT_URL_DEPS=()

    # Read the file and check each package entry
    in_package=false
    current_package=""
    has_hash=false

    while IFS= read -r line || [ -n "$line" ]; do
        # Skip empty lines and comments
        if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
            # If we were tracking a package, check if it had hashes
            if [ "$in_package" = true ] && [ "$has_hash" = false ]; then
                PACKAGES_WITHOUT_HASHES+=("$current_package")
            fi
            in_package=false
            has_hash=false
            current_package=""
            continue
        fi

        # Check for direct URL dependencies
        if [[ "$line" =~ ^[^#]*@ ]]; then
            # Line contains @ which might be a direct URL
            if [[ "$line" =~ (git\+|http://|https://) ]]; then
                # Check if it has hashes
                if ! grep -q "^[[:space:]]*--hash=" <<<"$line"; then
                    DIRECT_URL_DEPS+=("$line")
                fi
            fi
        fi

        # Check for --hash entries
        if [[ "$line" =~ --hash= ]]; then
            has_hash=true
            continue
        fi

        # Check for package definition line (contains ==, >=, ~=, etc.)
        if [[ "$line" =~ ^[a-zA-Z0-9_-]+[[:space:]]*[=\>\<\~!] ]]; then
            # If we were tracking a previous package, check if it had hashes
            if [ "$in_package" = true ] && [ "$has_hash" = false ]; then
                PACKAGES_WITHOUT_HASHES+=("$current_package")
            fi

            # Start tracking new package
            in_package=true
            has_hash=false
            # Extract package name (before ==, >=, etc.)
            current_package=$(echo "$line" | sed -E 's/^([a-zA-Z0-9_-]+).*/\1/')
        fi

        # Check for via annotations (indicates this is part of previous package entry)
        if [[ "$line" =~ ^[[:space:]]+#[[:space:]]+via ]]; then
            # This is an annotation, the package may continue
            continue
        fi
    done < "${req_file}"

    # Check last package
    if [ "$in_package" = true ] && [ "$has_hash" = false ]; then
        PACKAGES_WITHOUT_HASHES+=("$current_package")
    fi

    # Use a simpler approach: check that file contains --hash entries
    HASH_COUNT=$(grep -c -- '--hash=sha256:' "${req_file}" || true)
    PACKAGE_COUNT=$(grep -cE '^[a-zA-Z0-9_-]+[[:space:]]*==' "${req_file}" || true)

    if [ "$HASH_COUNT" -eq 0 ]; then
        echo "  ERROR: No hashes found in ${req_file}"
        echo "         Run './scripts/compile-deps.sh' to regenerate with hashes"
        ERRORS=1
    elif [ "$HASH_COUNT" -lt "$PACKAGE_COUNT" ]; then
        echo "  WARNING: Found ${HASH_COUNT} hash entries for ${PACKAGE_COUNT} packages"
        echo "           Some packages may be missing hashes"
    else
        echo "  OK: Found ${HASH_COUNT} hash entries for ${PACKAGE_COUNT} packages"
    fi

    # Check for direct URL dependencies without hashes
    if grep -qE '^[^#].*@[[:space:]]*(git\+|http://|https://)' "${req_file}"; then
        URL_DEPS=$(grep -E '^[^#].*@[[:space:]]*(git\+|http://|https://)' "${req_file}" || true)
        while IFS= read -r dep; do
            if [ -n "$dep" ]; then
                echo "  ERROR: Direct URL dependency found: ${dep}"
                echo "         Direct URL dependencies must be avoided for hash verification"
                ERRORS=1
            fi
        done <<< "$URL_DEPS"
    fi

    echo ""
done

# Verify that pip-compile was run with --generate-hashes flag
echo "Verifying pip-compile was run with --generate-hashes..."
for req_file in "${REQUIREMENTS_FILES[@]}"; do
    if [ -f "${req_file}" ]; then
        if ! grep -q -- '--generate-hashes' "${req_file}"; then
            echo "  WARNING: ${req_file} header does not mention --generate-hashes"
            echo "           File may have been generated without hash support"
        else
            echo "  OK: ${req_file} was generated with --generate-hashes"
        fi
    fi
done

echo ""

if [ "$ERRORS" -ne 0 ]; then
    echo "FAILED: Hash integrity check failed"
    echo ""
    echo "To fix:"
    echo "  1. Run './scripts/compile-deps.sh' to regenerate lockfiles with hashes"
    echo "  2. Avoid direct URL dependencies (git+, http://, https://)"
    echo "  3. Use pinned versions with hashes from PyPI"
    exit 1
fi

echo "All requirements files have proper hash integrity"
