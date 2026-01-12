#!/usr/bin/env bash
# check-python-version.sh - Validate Python version meets project requirements
# This function checks that the Python interpreter version is >= 3.11

check_python_version() {
    local python_cmd="${1:-python3}"

    # Get Python version
    local python_version
    python_version=$("${python_cmd}" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')

    # Extract major and minor version
    local major minor
    IFS='.' read -r major minor <<< "${python_version}"

    # Check minimum version (3.11)
    if [ "${major}" -lt 3 ] || { [ "${major}" -eq 3 ] && [ "${minor}" -lt 11 ]; }; then
        echo "ERROR: Python ${python_version} is not supported. This project requires Python 3.11 or higher." >&2
        echo "Please upgrade your Python installation or use a compatible version." >&2
        return 1
    fi

    echo "Using Python ${python_version}"
    return 0
}
