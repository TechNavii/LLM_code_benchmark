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

if ! python -c "import fastapi, pydantic_settings, requests, sqlalchemy, uvicorn" >/dev/null 2>&1; then
  echo "[devserver] Installing Python dependencies (with hash verification)"
  python -m pip install --disable-pip-version-check -q --upgrade pip
  python -m pip install --disable-pip-version-check -q --require-hashes -r "$ROOT_DIR/server/requirements.txt"
  python -m pip install --disable-pip-version-check -q --require-hashes -r "$ROOT_DIR/harness/requirements.txt"
fi

UVICORN_ARGS=(
  uvicorn
  server.api:app
)

CACHE_BUSTER="$(date +%s)"

cleanup() {
  if [ -n "${UVICORN_PID:-}" ] && kill -0 "$UVICORN_PID" >/dev/null 2>&1; then
    kill "$UVICORN_PID" >/dev/null 2>&1 || true
    wait "$UVICORN_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

"${UVICORN_ARGS[@]}" &
UVICORN_PID=$!

# Poll until uvicorn is answering before opening the browser
python <<'PY'
import socket
import time
import os

host = os.environ.get('DEVSERVER_HOST', '127.0.0.1')
port = int(os.environ.get('DEVSERVER_PORT', '8000'))

for _ in range(50):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        try:
            sock.connect((host, port))
        except OSError:
            time.sleep(0.2)
        else:
            break
PY

if [ -z "${DEVSERVER_NO_REFRESH:-}" ]; then
  python <<PY || true
import os
import webbrowser

host = os.environ.get('DEVSERVER_HOST', '127.0.0.1')
port = int(os.environ.get('DEVSERVER_PORT', '8000'))
cache_buster = os.environ.get('DEVSERVER_CACHE_BUSTER', '${CACHE_BUSTER}')
url = f"http://{host}:{port}/ui/index.html"

try:
    webbrowser.open(url, new=0, autoraise=True)
except Exception as exc:  # pragma: no cover - desktop environment issues
    print(f"[devserver] Failed to open browser automatically: {exc}")
PY
fi

wait "$UVICORN_PID"
