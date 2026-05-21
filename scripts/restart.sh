#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
LOG="${LOG:-/tmp/ydocter-server.log}"

echo "[restart] stopping existing uvicorn..."
pkill -f "uvicorn app.main:app" 2>/dev/null || true

for i in 1 2 3 4 5; do
  if ! pgrep -f "uvicorn app.main:app" >/dev/null; then break; fi
  sleep 0.5
done

if pgrep -f "uvicorn app.main:app" >/dev/null; then
  echo "[restart] forcing kill..."
  pkill -9 -f "uvicorn app.main:app" 2>/dev/null || true
  sleep 1
fi

echo "[restart] starting uvicorn on ${HOST}:${PORT} (log: ${LOG})"
# shellcheck disable=SC1091
source .venv/bin/activate
nohup uvicorn app.main:app --reload --host "$HOST" --port "$PORT" > "$LOG" 2>&1 &
PID=$!
disown "$PID" 2>/dev/null || true

for i in 1 2 3 4 5 6 7 8 9 10; do
  sleep 0.5
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://${HOST}:${PORT}/health" || true)"
  if [ "$code" = "200" ]; then
    echo "[restart] ok (pid=$PID, http=200)"
    exit 0
  fi
done

echo "[restart] FAILED — last 30 log lines:" >&2
tail -30 "$LOG" >&2
exit 1
