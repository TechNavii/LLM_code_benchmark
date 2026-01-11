#!/usr/bin/env bash
# Detect breaking API changes via OpenAPI diff (snapshot vs generated)
#
# Usage:
#   ./scripts/openapi-diff.sh           # Check for breaking changes
#   ./scripts/openapi-diff.sh --update  # Update the snapshot file (deliberate action)
#   ./scripts/openapi-diff.sh --strict  # Also fail on additive changes
#
# Exit codes:
#   0 - No changes or only additive changes (warn-only mode)
#   1 - Breaking changes detected
#   2 - Configuration/setup error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# Check Python version
source "$SCRIPT_DIR/check-python-version.sh"
check_python_version python3

# Ensure virtualenv exists and dependencies are installed
if [ ! -d ".venv" ]; then
    echo "Creating virtualenv..."
    python3 -m venv .venv
fi

echo "Ensuring dependencies are installed (with hash verification)..."
.venv/bin/pip install -q --require-hashes -r server/requirements.txt
.venv/bin/pip install -q --require-hashes -r requirements-dev.txt

SNAPSHOT_FILE="$REPO_ROOT/docs/openapi-snapshot.json"
UPDATE_MODE=false
STRICT_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --update)
            UPDATE_MODE=true
            shift
            ;;
        --strict)
            STRICT_MODE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--update] [--strict]"
            exit 2
            ;;
    esac
done

# Generate the OpenAPI schema
echo "Generating OpenAPI schema..."

GENERATED_SCHEMA=$(.venv/bin/python3 -c "
import json
import sys

# Import the app factory
from server.api import create_app

# Create the app instance
app = create_app()

# Get the OpenAPI schema (this is what FastAPI returns at /openapi.json)
schema = app.openapi()

# Output the schema as JSON
print(json.dumps(schema, indent=2, sort_keys=True))
")

if $UPDATE_MODE; then
    echo "Updating snapshot at $SNAPSHOT_FILE..."
    mkdir -p "$(dirname "$SNAPSHOT_FILE")"
    echo "$GENERATED_SCHEMA" > "$SNAPSHOT_FILE"
    echo "Snapshot updated successfully"
    exit 0
fi

# Check if snapshot exists
if [ ! -f "$SNAPSHOT_FILE" ]; then
    echo "ERROR: No snapshot file found at $SNAPSHOT_FILE"
    echo "Run ./scripts/openapi-diff.sh --update to create the initial snapshot"
    exit 2
fi

# Run the diff analysis
echo "Comparing generated schema against snapshot..."

DIFF_RESULT=$(GENERATED_SCHEMA="$GENERATED_SCHEMA" .venv/bin/python3 << 'PYTHON_SCRIPT'
import json
import sys
from typing import Any

def deep_diff(old: Any, new: Any, path: str = "") -> tuple[list[str], list[str]]:
    """
    Compare two values and return (breaking_changes, additive_changes).

    Breaking changes:
    - Removed paths/endpoints
    - Removed required fields
    - Removed schema properties
    - Changed field types (narrowing)
    - Added required fields (without defaults)
    - Tightened validation (e.g., new pattern, reduced enum values)

    Additive changes:
    - New paths/endpoints
    - New optional fields
    - New schema properties (not required)
    - Loosened validation
    """
    breaking = []
    additive = []

    if type(old) != type(new):
        # Type change is potentially breaking
        breaking.append(f"{path}: type changed from {type(old).__name__} to {type(new).__name__}")
        return breaking, additive

    if isinstance(old, dict):
        old_keys = set(old.keys())
        new_keys = set(new.keys())

        # Check for removed keys
        for key in old_keys - new_keys:
            full_path = f"{path}.{key}" if path else key
            if path.startswith("paths") or key in ("required", "properties", "type"):
                breaking.append(f"{full_path}: removed")
            else:
                additive.append(f"{full_path}: removed (non-breaking)")

        # Check for added keys
        for key in new_keys - old_keys:
            full_path = f"{path}.{key}" if path else key
            if path.startswith("paths") or key == "properties":
                additive.append(f"{full_path}: added (additive)")
            elif key == "required":
                # Adding required fields is breaking
                breaking.append(f"{full_path}: added required fields")
            else:
                additive.append(f"{full_path}: added")

        # Recursively check common keys
        for key in old_keys & new_keys:
            full_path = f"{path}.{key}" if path else key
            sub_breaking, sub_additive = deep_diff(old[key], new[key], full_path)
            breaking.extend(sub_breaking)
            additive.extend(sub_additive)

    elif isinstance(old, list):
        # For arrays, check if items were removed (breaking) or added (additive)
        old_set = set(json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else str(item) for item in old)
        new_set = set(json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else str(item) for item in new)

        removed = old_set - new_set
        added = new_set - old_set

        # Special handling for 'required' arrays - removing required field is additive, adding is breaking
        if path.endswith(".required"):
            for item in removed:
                additive.append(f"{path}: '{item}' no longer required (additive)")
            for item in added:
                breaking.append(f"{path}: '{item}' now required (breaking)")
        else:
            if removed:
                breaking.append(f"{path}: items removed: {sorted(removed)}")
            if added:
                additive.append(f"{path}: items added: {sorted(added)}")

    elif old != new:
        # Scalar value changed
        if path.endswith(".type"):
            # Type changes are breaking
            breaking.append(f"{path}: changed from '{old}' to '{new}'")
        elif "pattern" in path or "enum" in path:
            # Validation changes need careful analysis
            breaking.append(f"{path}: validation changed from '{old}' to '{new}'")
        else:
            additive.append(f"{path}: value changed from '{old}' to '{new}'")

    return breaking, additive


def analyze_openapi_diff(old_schema: dict, new_schema: dict) -> dict:
    """
    Analyze differences between two OpenAPI schemas.

    Returns a dict with:
    - breaking_changes: list of breaking change descriptions
    - additive_changes: list of additive change descriptions
    - has_breaking: bool
    - has_additive: bool
    """
    # Get high-level path differences first
    old_paths = set(old_schema.get("paths", {}).keys())
    new_paths = set(new_schema.get("paths", {}).keys())

    removed_paths = old_paths - new_paths
    added_paths = new_paths - old_paths

    breaking_changes = []
    additive_changes = []

    # Removed paths are breaking
    for path in sorted(removed_paths):
        breaking_changes.append(f"paths.{path}: endpoint removed")

    # Added paths are additive
    for path in sorted(added_paths):
        additive_changes.append(f"paths.{path}: new endpoint added")

    # Check schema/component differences
    old_schemas = old_schema.get("components", {}).get("schemas", {})
    new_schemas = new_schema.get("components", {}).get("schemas", {})

    removed_schemas = set(old_schemas.keys()) - set(new_schemas.keys())
    added_schemas = set(new_schemas.keys()) - set(old_schemas.keys())

    for schema in sorted(removed_schemas):
        breaking_changes.append(f"components.schemas.{schema}: schema removed")

    for schema in sorted(added_schemas):
        additive_changes.append(f"components.schemas.{schema}: new schema added")

    # Deep diff on common paths
    for path in sorted(old_paths & new_paths):
        old_path_obj = old_schema["paths"][path]
        new_path_obj = new_schema["paths"][path]

        # Check for removed/added HTTP methods
        old_methods = set(old_path_obj.keys())
        new_methods = set(new_path_obj.keys())

        for method in old_methods - new_methods:
            breaking_changes.append(f"paths.{path}.{method}: method removed")

        for method in new_methods - old_methods:
            additive_changes.append(f"paths.{path}.{method}: new method added")

        # Deep diff on common methods
        for method in old_methods & new_methods:
            method_path = f"paths.{path}.{method}"
            sub_breaking, sub_additive = deep_diff(
                old_path_obj[method],
                new_path_obj[method],
                method_path
            )
            breaking_changes.extend(sub_breaking)
            additive_changes.extend(sub_additive)

    # Deep diff on common schemas
    for schema_name in sorted(set(old_schemas.keys()) & set(new_schemas.keys())):
        schema_path = f"components.schemas.{schema_name}"
        sub_breaking, sub_additive = deep_diff(
            old_schemas[schema_name],
            new_schemas[schema_name],
            schema_path
        )
        breaking_changes.extend(sub_breaking)
        additive_changes.extend(sub_additive)

    # Check info changes (version, title, etc. - non-breaking)
    if old_schema.get("info") != new_schema.get("info"):
        old_info = old_schema.get("info", {})
        new_info = new_schema.get("info", {})
        if old_info.get("version") != new_info.get("version"):
            additive_changes.append(
                f"info.version: changed from '{old_info.get('version')}' to '{new_info.get('version')}'"
            )
        if old_info.get("title") != new_info.get("title"):
            additive_changes.append(
                f"info.title: changed from '{old_info.get('title')}' to '{new_info.get('title')}'"
            )

    return {
        "breaking_changes": breaking_changes,
        "additive_changes": additive_changes,
        "has_breaking": len(breaking_changes) > 0,
        "has_additive": len(additive_changes) > 0
    }


# Load schemas
with open("docs/openapi-snapshot.json", "r") as f:
    snapshot = json.load(f)

import io
import os

# Read generated schema from environment
generated_json = os.environ.get("GENERATED_SCHEMA", "")
if not generated_json:
    print("ERROR: GENERATED_SCHEMA environment variable not set", file=sys.stderr)
    sys.exit(2)

generated = json.loads(generated_json)

# Analyze differences
result = analyze_openapi_diff(snapshot, generated)

# Output results
output = {
    "has_breaking": result["has_breaking"],
    "has_additive": result["has_additive"],
    "breaking_changes": result["breaking_changes"],
    "additive_changes": result["additive_changes"],
    "match": not result["has_breaking"] and not result["has_additive"]
}

print(json.dumps(output, indent=2))
PYTHON_SCRIPT
)

# Check exit status
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to analyze OpenAPI diff"
    exit 2
fi

# Parse results
HAS_BREAKING=$(echo "$DIFF_RESULT" | .venv/bin/python3 -c "import json,sys; print(json.load(sys.stdin)['has_breaking'])")
HAS_ADDITIVE=$(echo "$DIFF_RESULT" | .venv/bin/python3 -c "import json,sys; print(json.load(sys.stdin)['has_additive'])")
IS_MATCH=$(echo "$DIFF_RESULT" | .venv/bin/python3 -c "import json,sys; print(json.load(sys.stdin)['match'])")

if [ "$IS_MATCH" = "True" ]; then
    echo "✓ OpenAPI schema matches snapshot (no changes detected)"
    exit 0
fi

# Report breaking changes
if [ "$HAS_BREAKING" = "True" ]; then
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "⛔ BREAKING CHANGES DETECTED"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "$DIFF_RESULT" | .venv/bin/python3 -c "
import json, sys
data = json.load(sys.stdin)
for change in data['breaking_changes']:
    print(f'  ✗ {change}')
"
    echo ""
    echo "Breaking changes require explicit acknowledgment."
    echo "If these changes are intentional, update the snapshot:"
    echo "  ./scripts/openapi-diff.sh --update"
    echo ""
fi

# Report additive changes
if [ "$HAS_ADDITIVE" = "True" ]; then
    echo ""
    echo "───────────────────────────────────────────────────────────────"
    echo "ℹ️  ADDITIVE CHANGES DETECTED (warn-only)"
    echo "───────────────────────────────────────────────────────────────"
    echo ""
    echo "$DIFF_RESULT" | .venv/bin/python3 -c "
import json, sys
data = json.load(sys.stdin)
for change in data['additive_changes']:
    print(f'  + {change}')
"
    echo ""
    echo "To update the snapshot with these changes:"
    echo "  ./scripts/openapi-diff.sh --update"
    echo ""
fi

# Exit code logic
if [ "$HAS_BREAKING" = "True" ]; then
    echo "FAILED: Breaking API changes detected"
    exit 1
elif $STRICT_MODE && [ "$HAS_ADDITIVE" = "True" ]; then
    echo "FAILED: Additive changes detected (strict mode)"
    exit 1
else
    echo "PASSED: No breaking changes (additive changes are warn-only)"
    exit 0
fi
