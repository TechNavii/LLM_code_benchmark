#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$ROOT/workspace"
BIN="$ROOT/tests/sparse_matrix_tests"

mkdir -p "$ROOT/tests/build"

g++ -std=c++20 -O2 -Wall -Wextra -pedantic \
  "$WORKSPACE/sparse_matrix.cpp" \
  "$ROOT/tests/test_sparse_matrix.cpp" \
  -I"$WORKSPACE" \
  -o "$BIN"

"$BIN"
