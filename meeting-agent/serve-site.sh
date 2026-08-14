#!/usr/bin/env bash
# Run Meeting Scribe as a PUBLIC website that anyone can use.
#
#   ./serve-site.sh
#
# Safety design:
#  - Uses a SEPARATE data directory (data-public/), so your own meetings are
#    physically absent from the public site — not merely hidden.
#  - Each visitor gets a private session; they can only ever see their own
#    meetings, never another visitor's and never yours.
#  - Upload size / length / per-hour limits, because transcription runs on THIS
#    Mac's CPU.
#  - No password: public access is the point. Do not put private meetings here —
#    use ./run.sh (private, localhost) or ./serve-public.sh (password-protected).
set -euo pipefail
cd "$(dirname "$0")"

export PUBLIC_MODE=true
export MEETING_DATA_DIR="$(pwd)/data-public"
export APP_PASSWORD=""            # public by design
export DEFAULT_ENGINE=local
# Keep a stranger's upload from monopolising the machine.
export PUBLIC_MAX_UPLOAD_MB="${PUBLIC_MAX_UPLOAD_MB:-25}"
export PUBLIC_MAX_MINUTES="${PUBLIC_MAX_MINUTES:-10}"
export PUBLIC_MAX_PER_HOUR="${PUBLIC_MAX_PER_HOUR:-5}"
# A smaller model keeps the queue moving when several people use it at once.
export LOCAL_WHISPER_MODEL="${LOCAL_WHISPER_MODEL:-small}"

mkdir -p "$MEETING_DATA_DIR"

if [ ! -x bin/cloudflared ]; then
  echo "cloudflared missing — see serve-public.sh for the install command."
  exit 1
fi

LOG=$(mktemp -t meeting-site)
./.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
APP_PID=$!
sleep 5

./bin/cloudflared tunnel --url http://localhost:8000 --no-autoupdate >"$LOG" 2>&1 &
TUNNEL_PID=$!
cleanup() { kill "$APP_PID" "$TUNNEL_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "Starting public site…"
for _ in $(seq 1 30); do
  URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" | head -1 || true)
  [ -n "$URL" ] && break
  sleep 1
done

if [ -n "${URL:-}" ]; then
  echo
  echo "  PUBLIC SITE : $URL"
  echo "  Data dir    : $MEETING_DATA_DIR  (your private meetings are NOT here)"
  echo "  Limits      : ${PUBLIC_MAX_UPLOAD_MB}MB · ${PUBLIC_MAX_MINUTES}min · ${PUBLIC_MAX_PER_HOUR}/hour per visitor"
  echo
  echo "Keep this window open — closing it takes the site offline."
else
  echo "Tunnel did not report a URL; see $LOG"
fi
wait "$TUNNEL_PID"
