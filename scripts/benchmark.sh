#!/usr/bin/env bash
# Run performance regression benchmarks for critical hot paths
#
# Usage:
#   ./scripts/benchmark.sh              # Run benchmarks and display results
#   ./scripts/benchmark.sh --save       # Save baseline for future comparison
#   ./scripts/benchmark.sh --compare    # Compare against saved baseline
#   ./scripts/benchmark.sh --json       # Output JSON results
#   ./scripts/benchmark.sh --fail-threshold 20  # Fail on >20% regression
#
# This script runs pytest-benchmark tests for:
# - Patch normalization (_is_probably_valid_patch, _normalize_patch_format)
# - Database queries (get_session, list_runs, get_run)
# - Progress dispatch (publish_attempt, _append_event)

set -euo pipefail

cd "$(dirname "$0")/.."

# Source Python version check
. ./scripts/check-python-version.sh

VENV=".venv"
BENCHMARK_DIR=".benchmarks"
BASELINE_NAME="baseline"
FAIL_THRESHOLD="${FAIL_THRESHOLD:-20}"  # 20% regression threshold
SAVE_BASELINE=""
COMPARE_BASELINE=""
JSON_OUTPUT=""
EXTRA_ARGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --save)
            SAVE_BASELINE="1"
            shift
            ;;
        --compare)
            COMPARE_BASELINE="1"
            shift
            ;;
        --json)
            JSON_OUTPUT="1"
            shift
            ;;
        --fail-threshold)
            FAIL_THRESHOLD="$2"
            shift 2
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# Ensure virtualenv exists and install dependencies
if [[ ! -d "$VENV" ]]; then
    echo "Creating virtualenv at $VENV..."
    python3 -m venv "$VENV"
fi

echo "Installing dependencies..."
"$VENV/bin/pip" install --require-hashes -q -r requirements-dev.txt

# Create benchmark directory
mkdir -p "$BENCHMARK_DIR"

# Build benchmark arguments
BENCHMARK_ARGS=(
    "-m" "benchmark"
    "--benchmark-only"
    "--benchmark-warmup=on"
    "--benchmark-min-rounds=10"
    "--benchmark-disable-gc"
)

if [[ -n "$SAVE_BASELINE" ]]; then
    echo "Saving benchmark baseline..."
    BENCHMARK_ARGS+=("--benchmark-save=$BASELINE_NAME")
    BENCHMARK_ARGS+=("--benchmark-storage=$BENCHMARK_DIR")
fi

if [[ -n "$COMPARE_BASELINE" ]]; then
    if [[ -d "$BENCHMARK_DIR" ]] && ls "$BENCHMARK_DIR"/*"$BASELINE_NAME"* >/dev/null 2>&1; then
        echo "Comparing against saved baseline..."
        BENCHMARK_ARGS+=("--benchmark-compare=$BASELINE_NAME")
        BENCHMARK_ARGS+=("--benchmark-storage=$BENCHMARK_DIR")
        BENCHMARK_ARGS+=("--benchmark-compare-fail=mean:${FAIL_THRESHOLD}%")
    else
        echo "Warning: No baseline found at $BENCHMARK_DIR. Running without comparison."
    fi
fi

if [[ -n "$JSON_OUTPUT" ]]; then
    BENCHMARK_ARGS+=("--benchmark-json=${BENCHMARK_DIR}/results.json")
fi

# Add any extra args
BENCHMARK_ARGS+=("${EXTRA_ARGS[@]:-}")

echo "Running performance benchmarks..."
echo "Fail threshold: ${FAIL_THRESHOLD}% regression"
echo ""

# Run benchmarks
"$VENV/bin/pytest" tests/test_benchmarks.py "${BENCHMARK_ARGS[@]}" -v

echo ""
echo "Benchmarks complete!"

if [[ -n "$JSON_OUTPUT" ]]; then
    echo "JSON results saved to: $BENCHMARK_DIR/results.json"
fi

if [[ -n "$SAVE_BASELINE" ]]; then
    echo "Baseline saved to: $BENCHMARK_DIR/"
fi
