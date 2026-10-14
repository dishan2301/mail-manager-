#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"

for FILE in "$PID_FILE" "$FRONTEND_PID_FILE"; do
  if [[ -f "$FILE" ]]; then
    PID="$(cat "$FILE")"
    if kill -0 "$PID" 2>/dev/null; then kill "$PID"; echo "Stopped PID $PID"; fi
  fi
done
if command -v fuser >/dev/null 2>&1; then
  fuser -k 10000/tcp 8080/tcp >/dev/null 2>&1 || true
fi
pkill -f "$ROOT_DIR/frontend/node_modules/.bin/vite" >/dev/null 2>&1 || true

rm -f "$PID_FILE" "$FRONTEND_PID_FILE"
