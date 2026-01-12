#!/usr/bin/env bash
set -euo pipefail

# check-env-example-secrets.sh - Validate .env.example contains no secrets or environment-specific values
# This script ensures example configuration files are safe to commit to version control.
# IMPORTANT: This script NEVER prints suspected secret values, only key names and line numbers.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Source Python version check
source "${SCRIPT_DIR}/check-python-version.sh"
check_python_version python3

# Ensure virtualenv exists
VENV_DIR=".venv"
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtualenv at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
fi

echo "Checking .env.example files for secrets and environment-specific values..."

# Run the Python checker script
"${VENV_DIR}/bin/python" - << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
"""
Validate that .env.example files contain no secrets or environment-specific values.

This is a focused check for example configuration files, complementing the broader
check-hardcoded-values.sh scanner. It specifically ensures:
1. No real API keys, tokens, passwords, or secrets
2. No absolute filesystem paths
3. Sensitive fields use placeholder values (empty, "replace-with-*", "your-*-here", etc.)

SECURITY NOTE: This script only reports key names and line numbers. It NEVER prints
the actual values to avoid accidentally exposing secrets in CI logs.
"""

import re
import sys
from pathlib import Path


# Patterns that indicate a real secret value (not a placeholder)
SECRET_VALUE_PATTERNS = [
    # API key formats (OpenAI, Anthropic, OpenRouter, AWS, etc.)
    re.compile(r'^sk-[a-zA-Z0-9]{20,}$'),
    re.compile(r'^sk-ant-[a-zA-Z0-9\-]{20,}$'),
    re.compile(r'^or-[a-zA-Z0-9]{20,}$'),
    re.compile(r'^AKIA[0-9A-Z]{16}$'),
    re.compile(r'^ghp_[a-zA-Z0-9]{36}$'),  # GitHub PAT
    re.compile(r'^gho_[a-zA-Z0-9]{36}$'),  # GitHub OAuth
    re.compile(r'^glpat-[a-zA-Z0-9\-_]{20,}$'),  # GitLab PAT
    # Generic secret-looking values (long hex, base64, random strings)
    re.compile(r'^[a-f0-9]{32,}$', re.IGNORECASE),  # Long hex strings
    re.compile(r'^[A-Za-z0-9+/]{40,}={0,2}$'),  # Base64-encoded (40+ chars)
]

# Key names that should have placeholder values, not real values
# Note: We use word boundaries to avoid false positives like "MAX_TOKENS" (count, not auth token)
SENSITIVE_KEY_PATTERNS = [
    re.compile(r'(?i)\b(api[_-]?key|secret|password|credential)\b'),
    re.compile(r'(?i)\b(private[_-]?key|access[_-]?key)\b'),
    re.compile(r'(?i)\b(auth[_-]?token|bearer[_-]?token|access[_-]?token)\b'),
    re.compile(r'(?i)^[A-Z_]*_?API_?KEY$'),  # Ends with API_KEY
]

# Key names that look like they contain "token" but are not authentication tokens
SAFE_TOKEN_KEY_PATTERNS = [
    re.compile(r'(?i)max[_-]?tokens?'),  # MAX_TOKENS, max_token (count limits)
    re.compile(r'(?i)num[_-]?tokens?'),  # NUM_TOKENS (count)
    re.compile(r'(?i)token[_-]?limit'),  # TOKEN_LIMIT (count)
    re.compile(r'(?i)token[_-]?count'),  # TOKEN_COUNT (count)
]

# Patterns that indicate a safe placeholder value
PLACEHOLDER_PATTERNS = [
    re.compile(r'^$'),  # Empty value
    re.compile(r'^replace-with-', re.IGNORECASE),
    re.compile(r'^your[-_]', re.IGNORECASE),
    re.compile(r'[-_]here$', re.IGNORECASE),
    re.compile(r'^placeholder', re.IGNORECASE),
    re.compile(r'^example', re.IGNORECASE),
    re.compile(r'^xxx+$', re.IGNORECASE),
    re.compile(r'^\*+$'),
    re.compile(r'^<.+>$'),  # <your-key-here>
    re.compile(r'^\[.+\]$'),  # [your-key-here]
    re.compile(r'^\{.+\}$'),  # {your-key-here}
]

# Patterns for absolute filesystem paths (environment-specific)
ABSOLUTE_PATH_PATTERNS = [
    re.compile(r'^/Users/[a-zA-Z0-9_]+'),  # macOS
    re.compile(r'^/home/[a-zA-Z0-9_]+'),  # Linux
    re.compile(r'^[A-Za-z]:\\Users\\'),  # Windows
    re.compile(r'^/opt/'),
    re.compile(r'^/etc/'),
    re.compile(r'^/var/'),
]

# Safe URL patterns (not considered secrets)
SAFE_URL_PATTERNS = [
    re.compile(r'^https?://127\.0\.0\.1'),
    re.compile(r'^https?://localhost'),
    re.compile(r'^https?://[a-zA-Z0-9\-\.]+\.(ai|com|io|org|net)/'),  # Public API URLs
]

# Suppressions file path
SUPPRESSIONS_FILE = ".env-example-secrets-allowlist.txt"


def load_suppressions(repo_root: Path) -> set[tuple[str, str]]:
    """Load suppressions from allowlist file. Returns set of (filename, key_name) tuples."""
    suppressions = set()
    suppressions_path = repo_root / SUPPRESSIONS_FILE

    if suppressions_path.exists():
        for line in suppressions_path.read_text().splitlines():
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            # Format: filename:KEY_NAME # justification
            if ":" in line:
                parts = line.split("#", 1)[0].strip()
                if ":" in parts:
                    filename, key = parts.split(":", 1)
                    suppressions.add((filename.strip(), key.strip()))

    return suppressions


def is_placeholder(value: str) -> bool:
    """Check if a value looks like a placeholder."""
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.match(value):
            return True
    return False


def is_secret_value(value: str) -> bool:
    """Check if a value looks like a real secret."""
    for pattern in SECRET_VALUE_PATTERNS:
        if pattern.match(value):
            return True
    return False


def is_absolute_path(value: str) -> bool:
    """Check if a value is an absolute filesystem path."""
    for pattern in ABSOLUTE_PATH_PATTERNS:
        if pattern.match(value):
            return True
    return False


def is_safe_url(value: str) -> bool:
    """Check if a value is a safe URL (not a secret)."""
    for pattern in SAFE_URL_PATTERNS:
        if pattern.match(value):
            return True
    return False


def is_sensitive_key(key: str) -> bool:
    """Check if a key name suggests it should have a placeholder value."""
    # First check if it's a safe token key (like MAX_TOKENS)
    for pattern in SAFE_TOKEN_KEY_PATTERNS:
        if pattern.search(key):
            return False

    # Then check if it matches sensitive patterns
    for pattern in SENSITIVE_KEY_PATTERNS:
        if pattern.search(key):
            return True
    return False


def check_env_example(file_path: Path, suppressions: set[tuple[str, str]]) -> list[tuple[int, str, str]]:
    """
    Check an .env.example file for secrets and environment-specific values.

    Returns list of (line_number, key_name, issue_type).
    """
    findings = []
    filename = file_path.name

    try:
        content = file_path.read_text()
    except Exception:
        return findings

    for line_num, line in enumerate(content.splitlines(), 1):
        line = line.strip()

        # Skip comments and empty lines
        if not line or line.startswith("#"):
            continue

        # Parse KEY=value (handle quoted values)
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        # Remove surrounding quotes from value
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        # Check if suppressed
        if (filename, key) in suppressions:
            continue

        # Check for real secret values
        if is_secret_value(value):
            findings.append((line_num, key, "appears to contain a real secret"))
            continue

        # Check for absolute filesystem paths
        if is_absolute_path(value) and not is_safe_url(value):
            findings.append((line_num, key, "contains absolute filesystem path"))
            continue

        # Check if sensitive key has a non-placeholder value
        if is_sensitive_key(key) and value and not is_placeholder(value) and not is_safe_url(value):
            # Allow empty values and safe URLs for sensitive keys
            if len(value) > 0:
                findings.append((line_num, key, "sensitive key has non-placeholder value"))
                continue

    return findings


def main():
    """Main entry point."""
    repo_root = Path.cwd()

    print("=" * 70)
    print("Example Config Secrets Check")
    print("=" * 70)
    print()
    print("Validating that .env.example files contain no secrets or")
    print("environment-specific values.")
    print()

    # Find all .env.example files (using set to avoid duplicates)
    env_examples_set = set(repo_root.glob("**/.env.example"))
    env_examples_set.update(repo_root.glob("**/*.env.example"))

    # Filter out excluded directories
    excluded_dirs = [".git", ".venv", "__pycache__", "node_modules", "runs", "htmlcov"]
    env_examples = sorted([
        f for f in env_examples_set
        if not any(excluded in f.parts for excluded in excluded_dirs)
    ])

    if not env_examples:
        print("No .env.example files found.")
        print()
        print("check-env-example-secrets passed")
        sys.exit(0)

    print(f"Found {len(env_examples)} .env.example file(s):")
    for f in env_examples:
        print(f"  - {f.relative_to(repo_root)}")
    print()

    # Load suppressions
    suppressions = load_suppressions(repo_root)
    if suppressions:
        print(f"Loaded {len(suppressions)} suppression(s) from {SUPPRESSIONS_FILE}")
        print()

    # Check each file
    all_findings = []
    for file_path in env_examples:
        findings = check_env_example(file_path, suppressions)
        for line_num, key, issue in findings:
            rel_path = file_path.relative_to(repo_root)
            all_findings.append((str(rel_path), line_num, key, issue))

    if all_findings:
        print("ERRORS found:")
        for file_path, line_num, key, issue in all_findings:
            # NEVER print the actual value, only the key name and line number
            print(f"  {file_path}:{line_num} - {key}: {issue}")
        print()
        print("To suppress a finding, add it to .env-example-secrets-allowlist.txt:")
        print("  Format: filename:KEY_NAME # justification")
        print()
        print("ERROR: Example config contains secrets or environment-specific values.")
        sys.exit(1)
    else:
        print("No secrets or environment-specific values found.")
        print()
        print("check-env-example-secrets passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
PYTHON_SCRIPT

exit_code=$?
if [ $exit_code -eq 0 ]; then
    echo "check-env-example-secrets passed"
else
    exit $exit_code
fi
