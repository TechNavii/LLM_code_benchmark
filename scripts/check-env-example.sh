#!/usr/bin/env bash
set -euo pipefail

# check-env-example.sh - Verify .env.example is synchronized with pydantic-settings models
# This script introspects the Settings classes and checks that required env vars
# exist in .env.example. It only reports key names, never reveals actual secrets.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# Source Python version check
source "${SCRIPT_DIR}/check-python-version.sh"
check_python_version python3

# Ensure virtualenv exists and has dependencies
VENV_DIR=".venv"
if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtualenv at ${VENV_DIR}..."
    python3 -m venv "${VENV_DIR}"
fi

# Ensure dependencies are installed (use same pattern as lint.sh)
echo "Ensuring dependencies are installed..."
"${VENV_DIR}/bin/pip" install --quiet pydantic pydantic-settings 2>/dev/null || true

echo "Checking .env.example synchronization with pydantic-settings models..."

# Run the Python checker script
"${VENV_DIR}/bin/python" - << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
"""Check .env.example synchronization with pydantic-settings models."""

import sys
from pathlib import Path

# Add repository root to path
repo_root = Path(__file__).resolve().parents[0] if "__file__" in dir() else Path.cwd()
sys.path.insert(0, str(repo_root))

def get_env_vars_from_settings():
    """Extract environment variable names from pydantic-settings models."""
    from pydantic.fields import PydanticUndefined
    from server.config import Settings as ServerSettings
    from harness.config import HarnessSettings

    env_vars = {}

    def process_model(model_cls, source_name):
        """Process a pydantic model and extract env var info."""
        for name, field_info in model_cls.model_fields.items():
            # Check for validation_alias (explicit env var name)
            if hasattr(field_info, 'validation_alias') and field_info.validation_alias:
                env_name = field_info.validation_alias
            else:
                env_name = name.upper()

            # Determine if required: no default AND default is PydanticUndefined (...)
            # A field with default=None or default_factory is NOT required
            is_required = (
                field_info.default is PydanticUndefined and
                field_info.default_factory is None
            )

            # Skip nested settings objects (they have default_factory)
            if name in ('database', 'api', 'harness'):
                continue

            # Skip if already seen from a higher-priority model
            if env_name in env_vars:
                continue

            env_vars[env_name] = {
                'source': source_name,
                'required': is_required,
                'has_default': field_info.default is not PydanticUndefined or field_info.default_factory is not None
            }

    # Process both models (server takes precedence if there's overlap)
    process_model(ServerSettings, 'server/config.py:Settings')
    process_model(HarnessSettings, 'harness/config.py:HarnessSettings')

    return env_vars


def get_env_vars_from_example():
    """Extract environment variable names from .env.example."""
    env_example_path = Path('.env.example')
    if not env_example_path.exists():
        return set()

    env_vars = set()
    for line in env_example_path.read_text().splitlines():
        line = line.strip()
        # Skip comments and empty lines
        if not line or line.startswith('#'):
            continue
        # Extract variable name (before =)
        if '=' in line:
            var_name = line.split('=', 1)[0].strip()
            env_vars.add(var_name)

    return env_vars


def main():
    """Check .env.example synchronization."""
    errors = []
    warnings = []

    # Get env vars from both sources
    settings_vars = get_env_vars_from_settings()
    example_vars = get_env_vars_from_example()

    # Allowlist for known-valid extra keys in .env.example
    # These are documented options or aliases that don't map directly to Settings fields
    ALLOWLIST = {
        # Add any extra env vars that should be in .env.example but aren't in Settings
    }

    # Check for required settings vars missing from .env.example
    for var_name, info in settings_vars.items():
        if info['required'] and var_name not in example_vars:
            errors.append(f"MISSING: {var_name} (required by {info['source']}) not in .env.example")
        elif var_name not in example_vars:
            # Optional vars - just note them, don't fail
            pass

    # Check for stale/unknown vars in .env.example
    settings_var_names = set(settings_vars.keys())
    for var_name in example_vars:
        if var_name not in settings_var_names and var_name not in ALLOWLIST:
            # Warn about potentially stale keys
            warnings.append(f"UNKNOWN: {var_name} in .env.example not found in pydantic-settings models")

    # Report results
    print("=" * 60)
    print("Environment Variable Synchronization Check")
    print("=" * 60)
    print()

    print("Settings models scanned:")
    print("  - server/config.py:Settings")
    print("  - harness/config.py:HarnessSettings")
    print()

    print(f"Variables in settings models: {len(settings_vars)}")
    print(f"Variables in .env.example: {len(example_vars)}")
    print()

    if errors:
        print("ERRORS:")
        for error in errors:
            print(f"  {error}")
        print()

    if warnings:
        print("WARNINGS (brownfield-safe, non-blocking):")
        for warning in warnings:
            print(f"  {warning}")
        print()

    if not errors and not warnings:
        print("All checks passed.")
    elif not errors:
        print("No errors found. Warnings above are informational.")

    # Exit with error only if there are errors (missing required vars)
    if errors:
        print()
        print("ERROR: .env.example is missing required environment variables.")
        print("Please update .env.example to include the missing variables.")
        sys.exit(1)

    print()
    print("check-env-example passed")


if __name__ == "__main__":
    main()
PYTHON_SCRIPT

echo "✓ .env.example synchronization check passed"
