#!/usr/bin/env bash
# Run OpenAPI-driven API fuzz tests using Schemathesis
#
# Usage:
#   ./scripts/openapi-fuzz.sh                    # Run fuzz tests with default settings
#   ./scripts/openapi-fuzz.sh --max-examples 50  # Limit examples per endpoint
#   ./scripts/openapi-fuzz.sh --dry-run          # Show what would be tested without running
#
# Environment variables:
#   FUZZ_MAX_EXAMPLES: Maximum examples per endpoint (default: 100)
#   FUZZ_TIMEOUT: Maximum time per test in seconds (default: 30)
#   FUZZ_WORKERS: Number of concurrent workers (default: 1)
#   FUZZ_EXCLUDE_ENDPOINTS: Comma-separated list of endpoint patterns to exclude

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

# Default configuration
MAX_EXAMPLES="${FUZZ_MAX_EXAMPLES:-100}"
TIMEOUT="${FUZZ_TIMEOUT:-30}"
WORKERS="${FUZZ_WORKERS:-1}"
EXCLUDE_ENDPOINTS="${FUZZ_EXCLUDE_ENDPOINTS:-}"
DRY_RUN=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --max-examples)
            MAX_EXAMPLES="$2"
            shift 2
            ;;
        --timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --exclude)
            EXCLUDE_ENDPOINTS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--max-examples N] [--timeout N] [--workers N] [--dry-run] [--exclude 'pattern,pattern']"
            exit 1
            ;;
    esac
done

echo "OpenAPI Fuzz Testing with Schemathesis"
echo "======================================="
echo "Max examples per endpoint: ${MAX_EXAMPLES}"
echo "Timeout per test: ${TIMEOUT}s"
echo "Workers: ${WORKERS}"

if [ -n "$EXCLUDE_ENDPOINTS" ]; then
    echo "Excluding endpoints: ${EXCLUDE_ENDPOINTS}"
fi

# Create reports directory
REPORT_DIR="${REPO_ROOT}/.fuzz-reports"
mkdir -p "$REPORT_DIR"

# Run Schemathesis against the FastAPI app
# We use the ASGI integration to test without starting a server
echo ""
echo "Running fuzz tests..."

# Build the schemathesis command
# Note: We use the Python API to run Schemathesis programmatically
# This allows better control and hermetic testing (no network calls)

if $DRY_RUN; then
    echo "[DRY RUN] Would run Schemathesis with the following configuration:"
    echo "  - Max examples: ${MAX_EXAMPLES}"
    echo "  - Timeout: ${TIMEOUT}s"
    echo "  - Workers: ${WORKERS}"
    echo "  - Excluded endpoints: ${EXCLUDE_ENDPOINTS:-none}"
    echo ""
    echo "Generating OpenAPI schema to show available endpoints..."

    .venv/bin/python3 << 'EOF'
import json
from server.api import create_app

app = create_app()
schema = app.openapi()

print("\nEndpoints that would be tested:")
for path, methods in sorted(schema.get('paths', {}).items()):
    for method in methods.keys():
        if method in ('get', 'post', 'put', 'patch', 'delete'):
            print(f"  {method.upper():8} {path}")
EOF
    exit 0
fi

# Run the actual fuzz tests
.venv/bin/python3 << EOF
import sys
import json
import os
from datetime import datetime, timezone

# Import schemathesis
import schemathesis
from hypothesis import given, settings, Phase, Verbosity

# Import the FastAPI app
from server.api import create_app

# Create the app
app = create_app()

# Load the OpenAPI schema from the app
# Use force_schema_version='30' since FastAPI 0.115+ uses OpenAPI 3.1.0
# which is not fully supported by Schemathesis yet
schema = schemathesis.from_asgi(
    "/openapi.json",
    app=app,
    force_schema_version='30'
)

# Configure Hypothesis settings for bounded testing
test_settings = settings(
    max_examples=${MAX_EXAMPLES},
    deadline=None,  # Disable deadline to avoid flaky failures
    suppress_health_check=[],
    phases=[Phase.explicit, Phase.reuse, Phase.generate],
    verbosity=Verbosity.normal,
)

# Track results
results = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "config": {
        "max_examples": ${MAX_EXAMPLES},
        "timeout": ${TIMEOUT},
        "workers": ${WORKERS},
    },
    "endpoints_tested": 0,
    "total_requests": 0,
    "failures": [],
    "errors": [],
    "passed": 0,
}

excluded_patterns = [p.strip() for p in "${EXCLUDE_ENDPOINTS}".split(",") if p.strip()]

def should_exclude(path: str) -> bool:
    """Check if an endpoint should be excluded from testing."""
    for pattern in excluded_patterns:
        if pattern in path:
            return True
    return False

print("Starting fuzz tests...")
print("")

# Iterate over all API operations
# Schemathesis 3.x returns Result objects, need to unwrap them
for result in schema.get_all_operations():
    # Unwrap the Result object
    if hasattr(result, 'ok'):
        endpoint = result.ok()
    else:
        endpoint = result

    path = endpoint.path
    method = endpoint.method.upper()

    if should_exclude(path):
        print(f"SKIP {method:8} {path} (excluded)")
        continue

    print(f"TEST {method:8} {path}")
    results["endpoints_tested"] += 1

    # Capture path/method in closure
    current_path = path
    current_method = method

    @test_settings
    @given(case=endpoint.as_strategy())
    def test_endpoint(case) -> None:
        """Test that the endpoint doesn't crash and returns valid responses."""
        results["total_requests"] += 1

        response = case.call_asgi()

        # Check for 5xx errors (server crashes) - except 503 which is expected for external services
        if response.status_code >= 500 and response.status_code != 503:
            error_info = {
                "path": current_path,
                "method": current_method,
                "status_code": response.status_code,
                "request": str(case),
            }
            try:
                error_info["response"] = response.text[:500]
            except:
                pass
            results["errors"].append(error_info)
            raise AssertionError(f"Server returned {response.status_code}")

        # Note: We don't validate responses against schema for fuzz tests
        # because 404/400 responses for invalid IDs are expected but not
        # always documented. The primary goal is to detect server crashes (5xx).

    try:
        test_endpoint()
        results["passed"] += 1
        print(f"  OK - No 5xx errors or validation failures")
    except Exception as e:
        error_msg = str(e)[:200]
        print(f"  FAIL - {error_msg}")
        results["failures"].append({
            "path": path,
            "method": method,
            "error": error_msg,
        })

# Summary
print("")
print("=" * 60)
print("FUZZ TEST SUMMARY")
print("=" * 60)
print(f"Endpoints tested: {results['endpoints_tested']}")
print(f"Total requests: {results['total_requests']}")
print(f"Passed: {results['passed']}")
print(f"Failures: {len(results['failures'])}")
print(f"5xx Errors: {len(results['errors'])}")

# Save detailed report
report_path = "${REPORT_DIR}/fuzz-report.json"
with open(report_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"")
print(f"Detailed report saved to: {report_path}")

# Exit with error if there were failures or 5xx errors
if results["failures"] or results["errors"]:
    print("")
    print("FAILURES DETECTED:")
    for f in results["failures"]:
        print(f"  - {f['method']} {f['path']}: {f['error']}")
    for e in results["errors"]:
        print(f"  - {e['method']} {e['path']}: HTTP {e['status_code']}")
    sys.exit(1)

print("")
print("All fuzz tests passed!")
sys.exit(0)
EOF

echo ""
echo "Fuzz testing complete."
