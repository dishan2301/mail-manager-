#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${PYTHON_BIN:-}" ]]; then
  :
elif [[ -x "$HOME/.local/bin/python3.11" ]]; then
  PYTHON_BIN="$HOME/.local/bin/python3.11"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.11)"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.12)"
elif command -v python3.13 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.13)"
else
  PYTHON_BIN="/usr/bin/python3"
fi
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/.run"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
BACKEND_LOG_FILE="$RUN_DIR/backend.log"
API_URL="http://localhost:10000"
APP_URL="http://localhost:8080"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"

mkdir -p "$RUN_DIR"

# Clean only this app's fixed ports so stale Vite/uvicorn children cannot cause a blank or stale dashboard.
if command -v fuser >/dev/null 2>&1; then
  fuser -k 10000/tcp 8080/tcp >/dev/null 2>&1 || true
fi
pkill -f "$FRONTEND_DIR/node_modules/.bin/vite" >/dev/null 2>&1 || true
rm -f "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"

if [[ -f "$BACKEND_PID_FILE" ]]; then
  OLD_PID="$(cat "$BACKEND_PID_FILE")"
  FRONTEND_RUNNING=false
  if [[ -f "$FRONTEND_PID_FILE" ]] && kill -0 "$(cat "$FRONTEND_PID_FILE")" 2>/dev/null; then FRONTEND_RUNNING=true; fi
  if kill -0 "$OLD_PID" 2>/dev/null && [[ "$FRONTEND_RUNNING" == true ]]; then
    echo "Dashboard already running. Backend PID: $OLD_PID"
    echo "Open: $APP_URL"
    exit 0
  fi
  rm -f "$BACKEND_PID_FILE"
fi

if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]] || ! "$BACKEND_DIR/.venv/bin/uvicorn" --help >/dev/null 2>&1; then
  echo "Backend virtualenv missing or broken. Recreating backend/.venv..."
  rm -rf "$BACKEND_DIR/.venv"
  if ! "$PYTHON_BIN" -m venv "$BACKEND_DIR/.venv"; then
    rm -rf "$BACKEND_DIR/.venv"
    "$PYTHON_BIN" -m pip install --user --break-system-packages virtualenv
    "$PYTHON_BIN" -m virtualenv "$BACKEND_DIR/.venv"
  fi
  "$BACKEND_DIR/.venv/bin/python" -m pip install --upgrade pip
  "$BACKEND_DIR/.venv/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Missing frontend/node_modules. Installing frontend dependencies..."
  (
    cd "$FRONTEND_DIR"
    npm install
  )
fi

if [[ "${RUN_GO_BUILD:-0}" == "1" || ! -f "$FRONTEND_DIR/dist/index.html" ]]; then
  echo "Building frontend..."
  (
    cd "$FRONTEND_DIR"
    npm run build
  )
else
  echo "Using existing frontend/dist"
fi

echo "Starting backend API on $API_URL"
cd "$BACKEND_DIR"
./.venv/bin/python -m alembic upgrade head
setsid env \
  SCHEDULER_ENABLED="${SCHEDULER_ENABLED:-true}" \
  FRONTEND_URL="$APP_URL" \
  DASHBOARD_URL="$APP_URL" \
  GRAPH_REDIRECT_URI="$APP_URL/api/graph/oauth/callback" \
  GOOGLE_REDIRECT_URI="$APP_URL/api/gmail/oauth/callback" \
  ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 10000 \
  >"$BACKEND_LOG_FILE" 2>&1 < /dev/null &
BACKEND_PID=$!
cd "$ROOT_DIR"
echo "$BACKEND_PID" >"$BACKEND_PID_FILE"

echo "Starting dashboard on $APP_URL"
cd "$FRONTEND_DIR"
setsid npm run dev -- --host 127.0.0.1 --port 8080 \
  >"$RUN_DIR/frontend.log" 2>&1 < /dev/null &
FRONTEND_PID=$!
cd "$ROOT_DIR"
echo "$FRONTEND_PID" >"$FRONTEND_PID_FILE"

for _ in {1..20}; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "Backend failed. Log: $BACKEND_LOG_FILE"
    exit 1
  fi
  if curl -fsS "$API_URL/api/health" >/dev/null 2>&1 && curl -fsS "$APP_URL/" >/dev/null 2>&1; then
    echo "App running."
    echo "URL: $APP_URL"
    echo "Log: $BACKEND_LOG_FILE"
    exit 0
  fi
  sleep 1
done

echo "Backend started but health check failed."
echo "URL: $APP_URL"
echo "Log: $BACKEND_LOG_FILE"
