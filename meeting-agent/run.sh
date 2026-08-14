#!/usr/bin/env bash
# Start Meeting Scribe.
#   ./run.sh            -> private, this Mac only (http://localhost:8000)
#   ./run.sh --public   -> also reachable from your network / a tunnel
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "First run: creating virtualenv and installing dependencies…"
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
  echo
  echo "Core install done. For offline transcription + speaker labels also run:"
  echo "  ./.venv/bin/pip install -r requirements-local.txt"
fi

HOST=127.0.0.1
if [ "${1:-}" = "--public" ]; then
  HOST=0.0.0.0
  shift
  # Refuse to expose stored meetings without a password.
  PW=$(grep -E '^APP_PASSWORD=.+' .env 2>/dev/null | head -1 | cut -d= -f2- || true)
  if [ -z "${APP_PASSWORD:-}${PW}" ]; then
    echo "✋ Refusing to serve publicly with no password."
    echo "   Anyone reaching the URL could read every meeting you've recorded."
    echo "   Add a line to .env first, e.g.:  APP_PASSWORD=your-strong-password"
    exit 1
  fi
  IP=$(ipconfig getifaddr en0 2>/dev/null || echo "your-ip")
  echo "Serving on your network:  http://${IP}:8000   (login required)"
fi

exec ./.venv/bin/python -m uvicorn backend.main:app --host "$HOST" --port 8000 "$@"
