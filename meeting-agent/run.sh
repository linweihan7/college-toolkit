#!/usr/bin/env bash
# Start Meeting Scribe on http://localhost:8000
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

exec ./.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 "$@"
