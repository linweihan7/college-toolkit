#!/usr/bin/env bash
# Start Meeting Scribe AND a public Cloudflare tunnel, then print the URL.
#
#   ./serve-public.sh
#
# The app runs on this Mac (so meeting audio never leaves it) and the tunnel
# gives it a public https address. Login is required — set APP_PASSWORD in .env.
# Note: the free quick-tunnel URL changes every time you restart.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x bin/cloudflared ]; then
  echo "cloudflared missing. Install it with:"
  echo "  mkdir -p bin && curl -fsSL -o bin/c.tgz https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz && tar -xzf bin/c.tgz -C bin && rm bin/c.tgz && chmod +x bin/cloudflared"
  exit 1
fi

LOG=$(mktemp -t meeting-tunnel)
./run.sh --public &
APP_PID=$!
sleep 5

./bin/cloudflared tunnel --url http://localhost:8000 --no-autoupdate >"$LOG" 2>&1 &
TUNNEL_PID=$!
cleanup() { kill "$APP_PID" "$TUNNEL_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "Starting tunnel…"
for _ in $(seq 1 30); do
  URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" | head -1 || true)
  [ -n "$URL" ] && break
  sleep 1
done

if [ -n "${URL:-}" ]; then
  echo
  echo "  Public URL : $URL"
  echo "  Local URL  : http://localhost:8000"
  echo "  Login      : user 'admin' + your APP_PASSWORD from .env"
  echo
  echo "Keep this window open — closing it takes the site offline."
else
  echo "Tunnel did not report a URL; see $LOG"
fi
wait "$TUNNEL_PID"
