#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$ROOT/workspace"
TEST_BIN="$ROOT/tests/thread_pool_tests"

mkdir -p "$ROOT/tests/build"

g++ -std=c++20 -O2 -pthread \
  "$WORKSPACE/thread_pool.cpp" \
  "$ROOT/tests/test_thread_pool.cpp" \
  -I"$WORKSPACE" \
  -o "$TEST_BIN"

"$TEST_BIN"
