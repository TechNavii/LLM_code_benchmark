#!/usr/bin/env bash
# Validate and optionally snapshot the FastAPI OpenAPI schema
#
# Usage:
#   ./scripts/openapi-validate.sh           # Validate schema and check snapshot
#   ./scripts/openapi-validate.sh --update  # Update the snapshot file

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

echo "Ensuring dependencies are installed..."
.venv/bin/pip install -q -r server/requirements.txt
.venv/bin/pip install -q -r requirements-dev.txt

SNAPSHOT_FILE="$REPO_ROOT/docs/openapi-snapshot.json"
UPDATE_MODE=false

if [[ "${1:-}" == "--update" ]]; then
    UPDATE_MODE=true
fi

# Generate and validate the OpenAPI schema using a Python inline script
# This avoids network calls and task execution - just schema generation
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

echo "Validating OpenAPI schema against OpenAPI 3.x specification..."

# Validate the schema with openapi-spec-validator
echo "$GENERATED_SCHEMA" | .venv/bin/python3 -c "
import sys
import json
from openapi_spec_validator import validate

# Read schema from stdin
schema = json.load(sys.stdin)

# Validate - will raise if invalid
validate(schema)
print('Schema is valid OpenAPI 3.x')
"

echo "OpenAPI schema validation passed"

if $UPDATE_MODE; then
    echo "Updating snapshot at $SNAPSHOT_FILE..."
    mkdir -p "$(dirname "$SNAPSHOT_FILE")"
    echo "$GENERATED_SCHEMA" > "$SNAPSHOT_FILE"
    echo "Snapshot updated"
else
    # Compare with snapshot if it exists (warn-only for now)
    if [ -f "$SNAPSHOT_FILE" ]; then
        echo "Comparing against snapshot..."

        # Use Python to compare schemas (ignoring key order)
        .venv/bin/python3 -c "
import json
import sys

generated = json.loads('''$GENERATED_SCHEMA''')

with open('$SNAPSHOT_FILE', 'r') as f:
    snapshot = json.load(f)

if generated == snapshot:
    print('Schema matches snapshot')
else:
    # Find differences at the top level
    gen_paths = set(generated.get('paths', {}).keys())
    snap_paths = set(snapshot.get('paths', {}).keys())

    added = gen_paths - snap_paths
    removed = snap_paths - gen_paths

    if added:
        print(f'WARNING: New paths added: {sorted(added)}')
    if removed:
        print(f'WARNING: Paths removed: {sorted(removed)}')

    # Check for info changes
    if generated.get('info') != snapshot.get('info'):
        print('WARNING: API info metadata changed')

    # This is warn-only initially per requirements
    print('WARNING: OpenAPI schema has changed from snapshot')
    print('Run ./scripts/openapi-validate.sh --update to update the snapshot')
    # Exit 0 since we are warn-only initially
    sys.exit(0)
"
    else
        echo "No snapshot file found at $SNAPSHOT_FILE"
        echo "Run ./scripts/openapi-validate.sh --update to create initial snapshot"
    fi
fi

echo "OpenAPI validation complete"
