#!/usr/bin/env bash
set -euo pipefail

# check-hardcoded-values.sh - Scan for hardcoded secrets, absolute paths, and env-specific values
# This script helps prevent accidental commits of sensitive or environment-specific data.
# IMPORTANT: This script NEVER prints suspected secret values, only filenames and line numbers.

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

echo "Scanning for hardcoded secrets, absolute paths, and environment-specific values..."

# Run the Python checker script
"${VENV_DIR}/bin/python" - << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
"""
Scan repository for hardcoded secrets, absolute filesystem paths, and environment-specific values.

SECURITY NOTE: This script only reports file paths and line numbers. It NEVER prints
the actual matched content to avoid accidentally exposing secrets in CI logs.
"""

import re
import sys
from pathlib import Path


# Patterns for potential secrets (compiled for performance)
SECRET_PATTERNS = [
    # API keys with specific prefixes (common formats)
    (re.compile(r'\b(sk-[a-zA-Z0-9]{20,})\b'), "OpenAI-style API key"),
    (re.compile(r'\b(sk-ant-[a-zA-Z0-9-]{20,})\b'), "Anthropic-style API key"),
    (re.compile(r'\b(or-[a-zA-Z0-9]{20,})\b'), "OpenRouter-style API key"),
    # Generic secret assignments (key=value where value looks secret-like)
    (re.compile(r'(?:api[_-]?key|secret|password|token|credential)\s*[=:]\s*["\'][a-zA-Z0-9_\-]{16,}["\']', re.IGNORECASE), "Generic secret assignment"),
    # AWS keys
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), "AWS Access Key ID"),
    # Private keys in content
    (re.compile(r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----'), "Private key header"),
]

# Patterns for absolute filesystem paths (exclude test fixtures, relative paths, URLs)
# We look for paths that appear to be real filesystem locations, not example/test paths
ABSOLUTE_PATH_PATTERNS = [
    # Real user home directories (macOS, Linux, Windows)
    (re.compile(r'(?<![\w/\\])(/Users/[a-zA-Z0-9_]+(?:/[^\s"\'\)\]\},:;]+)?)'), "macOS user path"),
    (re.compile(r'(?<![\w/\\])(/home/[a-zA-Z0-9_]+(?:/[^\s"\'\)\]\},:;]+)?)'), "Linux user path"),
    (re.compile(r'(?<![a-zA-Z0-9])([A-Za-z]:\\Users\\[a-zA-Z0-9_]+(?:\\[^\s"\'\)\]\},:;]+)?)'), "Windows user path"),
    # System-specific paths that could indicate hardcoded locations
    (re.compile(r'(?<![\w/\\])(/opt/[a-zA-Z0-9_\-]+(?:/[^\s"\'\)\]\},:;]+)?)'), "System /opt path"),
    (re.compile(r'(?<![\w/\\])(/etc/[a-zA-Z0-9_\-\.]+)'), "System /etc path"),
]

# Patterns for environment-specific values that shouldn't be hardcoded
ENV_SPECIFIC_PATTERNS = [
    # Specific hostnames/IPs that aren't localhost
    (re.compile(r'(?<![\w\.@])(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\w\.])'), "Private IP address"),
    # Base64-encoded secrets (long base64 strings that look like encoded credentials)
    (re.compile(r'["\'][A-Za-z0-9+/]{64,}={0,2}["\']'), "Possible base64-encoded secret"),
]

# Files and directories to exclude from scanning
EXCLUDE_PATTERNS = [
    r'\.git/',
    r'\.venv/',
    r'__pycache__/',
    r'\.pytest_cache/',
    r'\.hypothesis/',
    r'\.mypy_cache/',
    r'\.ruff_cache/',
    r'runs/',
    r'tasks/[^/]+/workspace/',
    r'htmlcov/',
    r'node_modules/',
    r'\.coverage',
    r'coverage\.xml',
    r'junit\.xml',
    r'docs/sbom/',
    r'\.trivy-reports/',
    r'\.signatures/',
    # Lock files (contain hashes, not secrets)
    r'requirements.*\.txt$',
    # Generated files
    r'docs/openapi-snapshot\.json$',
    r'docs/license-inventory\.txt$',
]

# Known safe patterns to allowlist
ALLOWLIST_PATTERNS = [
    # Test file paths using /tmp (common in tests)
    r'/tmp/[a-zA-Z0-9_/\.]+',
    # Documentation examples
    r'# Example:.*',
    r'e\.g\.,?\s+.*',
    # URLs to APIs (not filesystem paths)
    r'https?://[^\s]+',
    # Localhost/loopback (safe defaults)
    r'127\.0\.0\.1',
    r'localhost',
    r'::1',
    # Test fixtures and mocks
    r'test_[a-zA-Z0-9_]+\.py',
    # Config default values that use relative paths (ROOT / "something")
    r'ROOT\s*/\s*["\'][a-zA-Z0-9_]+["\']',
    # Placeholder values
    r'replace-with-your-',
    r'your[-_]?api[-_]?key',
    r'your[-_]?secret',
    r'placeholder',
    r'example\.com',
    r'example\.test',
]

# Specific file allowlist for known false positives
FILE_ALLOWLIST = {
    ".env.example": ["Generic secret assignment"],  # Expected to have placeholder formats
    ".gitleaks.toml": ["OpenAI-style API key", "Generic secret assignment"],  # Pattern definitions
    "docs/SECURITY.md": ["Generic secret assignment"],  # Documentation about secrets
    "server/redaction.py": ["OpenAI-style API key", "Anthropic-style API key", "OpenRouter-style API key", "Generic secret assignment"],  # Redaction patterns
    "tests/test_log_redaction.py": ["OpenAI-style API key", "Anthropic-style API key", "OpenRouter-style API key", "Generic secret assignment"],  # Testing redaction
    ".hardcoded-values-allowlist.txt": ["*"],  # Meta-allowlist file
}


def should_exclude_file(file_path: Path, repo_root: Path) -> bool:
    """Check if a file should be excluded from scanning."""
    rel_path = str(file_path.relative_to(repo_root))
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, rel_path):
            return True
    return False


def is_allowlisted(line: str, file_path: Path, finding_type: str, repo_root: Path) -> bool:
    """Check if a finding is allowlisted."""
    # Check file-specific allowlist
    rel_path = str(file_path.relative_to(repo_root))
    if rel_path in FILE_ALLOWLIST:
        allowed_types = FILE_ALLOWLIST[rel_path]
        if "*" in allowed_types or finding_type in allowed_types:
            return True

    # Check pattern-based allowlist
    for pattern in ALLOWLIST_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return True

    return False


def load_custom_allowlist(repo_root: Path) -> list[tuple[str, str]]:
    """Load custom allowlist from .hardcoded-values-allowlist.txt."""
    allowlist_path = repo_root / ".hardcoded-values-allowlist.txt"
    custom_allowlist = []

    if allowlist_path.exists():
        for line in allowlist_path.read_text().splitlines():
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            # Format: file_path:line_pattern # justification
            if ":" in line:
                parts = line.split("#", 1)
                file_pattern = parts[0].strip()
                if ":" in file_pattern:
                    file_part, line_pattern = file_pattern.split(":", 1)
                    custom_allowlist.append((file_part.strip(), line_pattern.strip()))

    return custom_allowlist


def matches_custom_allowlist(file_path: Path, line: str, custom_allowlist: list[tuple[str, str]], repo_root: Path) -> bool:
    """Check if finding matches custom allowlist."""
    rel_path = str(file_path.relative_to(repo_root))
    for file_pattern, line_pattern in custom_allowlist:
        if file_pattern in rel_path:
            try:
                if re.search(line_pattern, line):
                    return True
            except re.error:
                # If pattern is invalid, treat as literal match
                if line_pattern in line:
                    return True
    return False


def scan_file(file_path: Path, repo_root: Path, custom_allowlist: list[tuple[str, str]]) -> list[tuple[int, str]]:
    """Scan a single file for hardcoded values. Returns list of (line_number, finding_type)."""
    findings = []

    try:
        content = file_path.read_text(errors="ignore")
    except Exception:
        return findings

    lines = content.splitlines()

    for line_num, line in enumerate(lines, 1):
        # Skip comment lines (Python, bash, JS)
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("/*"):
            continue

        # Check secret patterns
        for pattern, finding_type in SECRET_PATTERNS:
            if pattern.search(line):
                if not is_allowlisted(line, file_path, finding_type, repo_root):
                    if not matches_custom_allowlist(file_path, line, custom_allowlist, repo_root):
                        findings.append((line_num, finding_type))
                        break  # Only report one finding per line

        # Check absolute path patterns (only in non-test files for real paths)
        if "/test" not in str(file_path).lower():
            for pattern, finding_type in ABSOLUTE_PATH_PATTERNS:
                if pattern.search(line):
                    if not is_allowlisted(line, file_path, finding_type, repo_root):
                        if not matches_custom_allowlist(file_path, line, custom_allowlist, repo_root):
                            # Skip if it's in a string that looks like a test fixture
                            if '/tmp/' not in line:
                                findings.append((line_num, finding_type))
                                break

        # Check environment-specific patterns (less strict, warn only)
        for pattern, finding_type in ENV_SPECIFIC_PATTERNS:
            if pattern.search(line):
                if not is_allowlisted(line, file_path, finding_type, repo_root):
                    if not matches_custom_allowlist(file_path, line, custom_allowlist, repo_root):
                        # Private IPs are warnings unless in config files
                        if "config" not in str(file_path).lower():
                            findings.append((line_num, f"WARNING: {finding_type}"))
                            break

    return findings


def scan_repository(repo_root: Path) -> dict[str, list[tuple[int, str]]]:
    """Scan the repository for hardcoded values."""
    all_findings = {}
    custom_allowlist = load_custom_allowlist(repo_root)

    # Scan Python files
    for pattern in ["**/*.py", "**/*.sh", "**/*.js", "**/*.json", "**/*.toml", "**/*.yaml", "**/*.yml"]:
        for file_path in repo_root.glob(pattern):
            if should_exclude_file(file_path, repo_root):
                continue
            if not file_path.is_file():
                continue

            findings = scan_file(file_path, repo_root, custom_allowlist)
            if findings:
                rel_path = str(file_path.relative_to(repo_root))
                all_findings[rel_path] = findings

    return all_findings


def main():
    """Main entry point."""
    repo_root = Path.cwd()

    print("=" * 70)
    print("Hardcoded Values Scan")
    print("=" * 70)
    print()
    print("Scanning for:")
    print("  - Hardcoded secrets (API keys, tokens, passwords)")
    print("  - Absolute filesystem paths (user home dirs, system paths)")
    print("  - Environment-specific values (private IPs, encoded secrets)")
    print()
    print("Excludes: .git, .venv, runs/, tasks/*/workspace/, caches, lockfiles")
    print()

    findings = scan_repository(repo_root)

    errors = []
    warnings = []

    for file_path, file_findings in sorted(findings.items()):
        for line_num, finding_type in file_findings:
            if finding_type.startswith("WARNING:"):
                warnings.append(f"  {file_path}:{line_num} - {finding_type}")
            else:
                errors.append(f"  {file_path}:{line_num} - {finding_type}")

    if errors:
        print("ERRORS (blocking):")
        for error in errors:
            print(error)
        print()

    if warnings:
        print("WARNINGS (non-blocking):")
        for warning in warnings:
            print(warning)
        print()

    total = len(errors) + len(warnings)
    if total == 0:
        print("No hardcoded values found.")
        print()
        print("check-hardcoded-values passed")
        sys.exit(0)
    elif errors:
        print(f"Found {len(errors)} error(s) and {len(warnings)} warning(s).")
        print()
        print("To suppress a finding, add it to .hardcoded-values-allowlist.txt with justification.")
        print("Format: file_path:regex_pattern # justification")
        print()
        print("ERROR: Hardcoded values detected. Please remove them or add justified suppressions.")
        sys.exit(1)
    else:
        print(f"Found {len(warnings)} warning(s) (non-blocking).")
        print()
        print("check-hardcoded-values passed (warnings only)")
        sys.exit(0)


if __name__ == "__main__":
    main()
PYTHON_SCRIPT

exit_code=$?
if [ $exit_code -eq 0 ]; then
    echo "check-hardcoded-values passed"
else
    exit $exit_code
fi
