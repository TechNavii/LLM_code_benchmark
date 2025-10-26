#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
ENV_FILE="$ROOT_DIR/.env"

if [ ! -d "$VENV_DIR" ]; then
  echo "[qa-devserver] Creating virtual environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# uvicorn expects to import the server package from the repo root
cd "$ROOT_DIR"

if [ -z "${OPENROUTER_API_KEY:-}" ] && [ -f "$ENV_FILE" ]; then
  OPENROUTER_API_KEY="$(ENV_FILE="$ENV_FILE" python <<'PY'
import os
from pathlib import Path

env_path = Path(os.environ['ENV_FILE'])
value = ''
for raw_line in env_path.read_text(encoding='utf-8').splitlines():
    line = raw_line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, val = line.split('=', 1)
    if key.strip() == 'OPENROUTER_API_KEY':
        value = val.strip().strip('"').strip("'")
        break
if value:
    print(value, end='')
PY
)"
  if [ -n "$OPENROUTER_API_KEY" ]; then
    export OPENROUTER_API_KEY
    echo "[qa-devserver] OPENROUTER_API_KEY loaded from .env"
  fi
fi

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "[qa-devserver] WARNING: OPENROUTER_API_KEY is not set; API calls will fail." >&2
fi

DEVSERVER_HOST="${DEVSERVER_HOST:-127.0.0.1}"
if [ -z "${DEVSERVER_PORT:-}" ]; then
  DEVSERVER_PORT="$(DEVSERVER_HOST="$DEVSERVER_HOST" python <<'PY'
import os
import socket
import contextlib

host = os.environ['DEVSERVER_HOST']

def is_free(port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(0.1)
        return sock.connect_ex((host, port)) != 0

port = 8000
if not is_free(port):
    for candidate in range(8001, 8101):
        if is_free(candidate):
            port = candidate
            break
    else:
        port = -1

if port > 0:
    print(port, end='')
PY
)"
  if [ -z "$DEVSERVER_PORT" ]; then
    echo "[qa-devserver] ERROR: no free port found in range 8000-8100." >&2
    exit 1
  fi
  export DEVSERVER_PORT
  if [ "$DEVSERVER_PORT" != "8000" ]; then
    echo "[qa-devserver] Port 8000 busy; using ${DEVSERVER_PORT}."
  fi
fi

export DEVSERVER_HOST DEVSERVER_PORT

if ! python -c "import requests" >/dev/null 2>&1; then
  echo "[qa-devserver] Installing Python dependencies"
  python -m pip install --disable-pip-version-check -q --upgrade pip
  python -m pip install --disable-pip-version-check -q -r "$ROOT_DIR/server/requirements.txt"
  python -m pip install --disable-pip-version-check -q -r "$ROOT_DIR/harness/requirements.txt" || true
  python -m pip install --disable-pip-version-check -q requests
fi

UVICORN_ARGS=(
  uvicorn
  server.api:app
  --host "${DEVSERVER_HOST}"
  --port "${DEVSERVER_PORT}"
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
url = f"http://{host}:{port}/ui/qa/index.html"

try:
    webbrowser.open(url, new=0, autoraise=True)
except Exception as exc:  # pragma: no cover - desktop environment issues
    print(f"[qa-devserver] Failed to open browser automatically: {exc}")
PY
fi

wait "$UVICORN_PID"
