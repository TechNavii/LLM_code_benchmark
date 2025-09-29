#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "[devserver] Creating virtual environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# uvicorn expects to import the server package from the repo root
cd "$ROOT_DIR"

if ! python -c "import requests" >/dev/null 2>&1; then
  echo "[devserver] Installing Python dependencies"
  python -m pip install --disable-pip-version-check -q --upgrade pip
  python -m pip install --disable-pip-version-check -q -r "$ROOT_DIR/server/requirements.txt"
  python -m pip install --disable-pip-version-check -q -r "$ROOT_DIR/harness/requirements.txt" || true
  python -m pip install --disable-pip-version-check -q requests
fi

exec uvicorn server.api:app --reload \
  --reload-exclude '.venv/*' \
  --reload-exclude 'runs/*'
